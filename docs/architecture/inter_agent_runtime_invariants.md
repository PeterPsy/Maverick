# Inter-Agent Runtime Invariants

Date: 2026-06-17
Status: Accepted through F4

## Purpose

This ADR fixes the runtime invariants required before Maverick can create real multi-agent child sessions.

It started with names, visibility, legacy compatibility, and initial policy defaults. F2 extends it with the first policy-aware participant spawn, message, wait, interrupt, resume, close, and recovery surfaces for hidden child runtime sessions. F3 adds the native MVP executor for `manager_tools`, `sequential`, and `concurrent` runs while keeping graph mode, adapters, and handoff execution out of scope. F4 adds the initial Chat UX wiring, inline approvals, and graph entry links while keeping runtime execution inside core-owned inter-agent APIs.

## Decisions

1. The initial code domain is `core/inter_agent`. The product language is "multi-agent orchestration".
2. `InterAgentRun` remains the run record name for the MVP. A broader `core/orchestration` rename requires a later ADR after real usage data.
3. Runtime sessions carry `session_kind` with values `chat_root`, `inter_agent_participant`, and `system`.
4. Runtime sessions carry `thread_visibility` with values `user` and `hidden`.
5. Legacy runtime session records that omit either field are interpreted as `session_kind="chat_root"` and `thread_visibility="user"`.
6. Only `thread_visibility="user"` sessions may produce `RuntimeThreadRecord` records or appear in Chat thread catalogs.
7. `thread_visibility="hidden"` sessions may have runtime turns, runtime events, runtime processes, provider state, and runtime roots, but they must not create, update, or appear as user-visible runtime threads.
8. `session_kind="inter_agent_participant"` requires `thread_visibility="hidden"`; omitted visibility on an explicit participant is normalized to hidden, while explicit `user` visibility is invalid.
9. Invalid persisted visibility values fail closed: they are rejected on direct session hydration and must not make an existing thread appear in user-facing thread catalogs.
10. `handoff` is schema/event-only until F7. It is not executable MVP behavior unless a later ADR explicitly promotes it.
11. The F3 native executor may run deterministic synthetic participants only for tests or explicit operator-controlled execution, or real hidden child runtime sessions through the F2 service. It must not bypass inter-agent spawn, message, budget, or root-session authority checks.
12. The root Chat transcript receives only selected operational summaries from the executor as non-terminal `runtime.step.updated` projections. `runtime.output.final` is reserved for real assistant final answers.
13. Full participant detail remains in `inter_agent` events for graph replay and audit, but event replay and run detail require creator, root-session owner, admin, operator, or explicit `inter_agent_root` grant authority and must cap `summary`/`detail`/`debug` server-side.
14. Chat may request a persisted root transcript projection for an inter-agent execution by sending a `client_message_id` to `POST /api/inter-agent/runs/<run_id>/execute`. The projection records the user's root turn and bounded runtime lifecycle events on the visible root session; it does not expose hidden participant sessions or duplicate the full inter-agent event log.

## Initial Policy Defaults

Budget policy starts fail-closed and run-scoped:

- non-`single_agent` runs must declare max participants and max concurrent participants
- spawn, handoff, fan-out, and runtime turn submission require core budget accounting before work starts
- reservations and releases must be idempotent
- participant/concurrency reservations are released on interrupt or close, while successfully submitted runtime turns remain consumed so `max_total_turns` cannot be bypassed by repeated message sends
- turn, per-participant turn, tool-call, estimated-token, estimated-cost, idle, and stall limits are enforced by the core
- pause and cancellation remain available even when budget is exhausted

Approval policy starts user-safe and workspace-aware:

- the run creator may approve ordinary operations for that run unless workspace policy is stricter
- workspace admins may approve sensitive operations only when governance allows it
- runtime participants cannot self-approve sensitive writes, secret delivery, or cross-app operations
- sensitive approval timeout fails closed
- rejected or expired approvals produce inter-agent events and leave the participant blocked or force orchestrator replan

Retention policy is separated by inter-agent visibility plane:

- `summary` events are retained longest because they are user-facing audit material
- `detail` events have medium retention for graph replay and operational inspection
- `debug` events have the shortest retention and require stricter authorization

## Runtime Thread Invariant

The old invariant "every runtime session has exactly one runtime thread" is replaced.

The new invariant is:

- every user-visible chat runtime session has exactly one runtime thread before Chat catalogs are returned
- hidden inter-agent participant sessions have no runtime thread
- direct thread-open or thread-create calls for hidden sessions fail with `runtime_session_hidden`
- thread catalogs and `WS /ws/runtime/threads` expose only user-visible runtime threads

This keeps the primary Chat transcript as one visible conversation while allowing participant sessions to execute without appearing as standalone chats.

## Child Session Helper Boundary

The internal `create_child_runtime_session` helper is not the public multi-agent spawn API.

It may reuse only the parent session's resolved workspace boundary, workdir, execution mode, and runtime-session parent linkage. Prompt materialization, skill ids, skill catalog, source app, owner, creator, and operation grants must be explicit inputs produced by core policy, an authorized app snapshot, or a later `ParticipantSpec` materialization step. The helper defaults those authority-bearing fields to empty values and must not clone them from the parent session. Platform operation grants must be typed `RuntimeSessionGrantRecord` values minted by core policy; public payload dictionaries, even with `source="platform"`, are not grant material.

Runtime session ids are path-bearing identifiers and must validate as a single safe basename before runtime roots are created or deleted. Caller-supplied child session ids may be accepted only after the core runtime path helper rejects absolute paths, `..`, separators, empty values, and other non-basename input. Runtime cleanup must validate the session id before terminating or deleting records, and must refuse to delete any resolved runtime root that does not match the canonical workspace `runtime/sessions/<session_id>` root.

## F2 Runtime Access Policy

F0 models the visibility boundary and blocks thread creation for hidden sessions. F2 applies server-side visibility policy to raw runtime session access paths before real participant sessions are exposed outside tests:

- `GET /api/runtime/sessions`
- `GET /api/runtime/sessions/<session_id>`
- `GET /api/runtime/sessions/<session_id>/events`
- `GET /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/cleanup`
- `GET /api/runtime/turns/<turn_id>`
- `POST /api/runtime/turns/<turn_id>/interrupt`
- `WS /ws/runtime/sessions/<session_id>`
- CLI and MCP runtime status surfaces

App-owned runtime launch, interrupt, and cleanup requests are also raw runtime paths for this purpose. If they name an existing hidden participant session or a turn belonging to one, they must fail closed and leave operation to `InterAgentService`.

The only public F2 creation path for `inter_agent_participant` sessions is the core-owned inter-agent surface. HTTP uses `/api/inter-agent/runs/<run_id>/participants`; CLI uses `inter-agent.participants.spawn`; MCP uses `inter_agent_participant_spawn`. All three must route through the policy-aware service, require run creator/owner or admin authority for mutations, and must not call `create_child_runtime_session` with parent-copied or user-payload authority. Public run/spawn payloads may name topology, participant id, child session id, and owner under policy; they must not materialize prompt text, skill ids, skill catalog, source app, provider selection, agent snapshots, or runtime operation grants. Source app for a public inter-agent run is derived from the root runtime session, not from the caller payload. A non-operator caller may attach a run to a root runtime session only when they own that root, are an admin, or hold an explicit platform-minted `inter_agent_root` grant; workspace membership alone is not sufficient.

Inter-agent close over HTTP, CLI, and MCP must use the full runtime cleanup path when full platform state is available. Hidden child cleanup may be allowed only for this inter-agent service path; raw runtime cleanup remains hidden-session-blocked. Fallback store-only termination is reserved for deliberately partial test or recovery state and must not be the normal hosted CLI/MCP behavior.

## F3 Native Executor Policy

The initial native executor is a core-owned MVP surface, not an adapter framework.

Executable modes:

- `manager_tools`
- `sequential`
- `concurrent`

Execution rules:

- deterministic synthetic participants are allowed only for tests or explicit operator-controlled execution
- public HTTP execution must not accept caller-supplied controlled participant output; CLI and MCP require an operator caller plus explicit synthetic opt-in
- synthetic participant events, execution results, summary-plane updates, and root transcript projections must be marked explicitly with their synthetic source
- real participant work must use hidden `child_runtime_session` sessions spawned through `InterAgentService`
- `sequential` passes declared output from one participant into the next participant input
- `concurrent` fans out participants under `max_concurrent_participants` and then aggregates through the root orchestrator or declared aggregator participant
- participant/task/artifact/summary/run lifecycle events are persisted as normalized `inter_agent` events
- artifact refs and partial output must be persisted before a participant failure is recorded
- root runtime projection is limited to selected summaries such as plan and terminal synthesis and must use non-terminal runtime step updates
- successfully consumed turns stay counted in the budget ledger; only active participant/concurrency reservations are released on participant completion or failure
- pre-participant-ledger turn reservations and matching `inter_agent.budget.reserved` events without `participant_id` must remain idempotent on retry and must still count toward per-participant turn enforcement, using reservation id inference where possible and conservative counting otherwise

The F3 HTTP surface is `POST /api/inter-agent/runs/<run_id>/execute`. The matching CLI command is `inter-agent.runs.execute`, and the matching MCP tool is `inter_agent_execute`.

## F4 Chat UX Policy

The initial Chat UX is a client of the core-owned inter-agent surfaces. It may create runs, execute runs, list summary-plane run events, list approvals, resolve approvals, and open graph links. It must not create participant runtime sessions directly, read hidden runtime session APIs, or implement a parallel executor in the frontend.

HTTP additions for F4:

- `GET /api/inter-agent/runs/<run_id>/approvals` lists approval records for an authorized run viewer and expires stale pending approvals fail-closed before returning records.
- `POST /api/inter-agent/approvals/<approval_id>/resolve` approves or rejects one pending approval through `InterAgentService.resolve_approval`; missing approvals return `inter_agent_approval_not_found`.
- `POST /api/inter-agent/runs/<run_id>/execute` may include `client_message_id`, `attachments`, and `app_references` for Chat root transcript projection. Without `client_message_id`, the F3 execute response shape remains unchanged.

Chat transcript rendering remains summary-first:

- composer state is a UI selector for Off, Auto, or Multi; non-Off submissions still call core `inter_agent` APIs
- run banners and orchestrator messages render only core-provided summaries
- inline approvals read and resolve core approval records
- graph links carry `inter_agent_run_id` for the F5 graph surface; F4 does not implement graph replay or WebSocket graph streaming
- raw chain-of-thought, debug events, and hidden participant transcripts remain out of the primary Chat transcript

## Gate

No later phase may bypass the inter-agent service when creating real child runtime sessions. Hidden thread visibility and raw runtime access rejection must remain covered by runtime-thread, runtime HTTP, WebSocket, cleanup, and inter-agent service/API tests. Adapter phases must map back into the same run, participant, budget, artifact, and event contracts rather than owning Maverick session or secret state.
