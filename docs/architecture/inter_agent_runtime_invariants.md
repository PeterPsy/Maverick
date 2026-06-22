# Inter-Agent Runtime Invariants

Date: 2026-06-17
Status: Accepted through F7

## Purpose

This ADR fixes the runtime invariants required before Maverick can create real multi-agent child sessions.

It started with names, visibility, legacy compatibility, and initial policy defaults. F2 extends it with the first policy-aware participant spawn, message, wait, interrupt, resume, close, and recovery surfaces for hidden child runtime sessions. F3 adds the native MVP executor for `manager_tools`, `sequential`, and `concurrent` runs while keeping adapters and handoff execution out of scope. F4 adds the initial Chat UX wiring, inline approvals, and graph entry links while keeping runtime execution inside core-owned inter-agent APIs. F5 adds Chat graph mode backed by core-owned inter-agent replay and live stream surfaces. F7 promotes `group_chat` as the first advanced product-facing mode behind explicit feature flags.

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
10. `group_chat` is the first advanced mode promoted for F7 product use, but
    only behind `MAVERICK_FEATURE_GROUP_CHAT=1` for public HTTP/CLI/MCP
    inter-agent surfaces and `VITE_MAVERICK_FEATURE_GROUP_CHAT=1` for the Chat
    frontend build. The
    accepted F7 decision is recorded in
    [inter_agent_group_chat_f7.md](inter_agent_group_chat_f7.md). `handoff`
    and `magentic_like` remain schema/event-only and are not executable product
    behavior unless a later ADR explicitly promotes them. The F6 MAF
    source-backed adapter evaluation may execute `handoff`, `group_chat`, and
    `magentic_like` fixtures only behind
    `MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK=1`; that exception is not default-on,
    not product-facing Chat behavior, and must still project only
    Maverick-owned run, participant, edge, event, budget, approval, artifact,
    and root transcript records.
11. The F3 native executor may run deterministic synthetic participants only for tests or explicit operator-controlled execution, or real hidden child runtime sessions through the F2 service. It must not bypass inter-agent spawn, message, budget, or root-session authority checks.
12. The root Chat transcript receives selected operational summaries from the executor as non-terminal `runtime.step.updated` projections. When Chat requests a persisted root turn projection, the final assistant answer must be projected as `runtime.output.final` on that root turn, while detailed participant work remains in `inter_agent` events.
13. Full participant detail remains in `inter_agent` events for graph replay and audit, but event replay and run detail require creator, root-session owner, admin, operator, or explicit `inter_agent_root` grant authority and must cap `summary`/`detail`/`debug` server-side.
14. Chat may request a persisted root transcript projection for an inter-agent execution by sending a `client_message_id` to `POST /api/inter-agent/runs/<run_id>/execute`. The projection records the user's root turn, bounded runtime lifecycle events, and the final answer on the visible root session; it does not expose hidden participant sessions or duplicate the full inter-agent event log.
15. Graph mode consumes `inter_agent` events, run detail, approvals, and artifacts through core-owned replay and live surfaces. It must not read hidden runtime sessions directly.

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

The only public F2 creation path for `inter_agent_participant` sessions is the core-owned inter-agent surface. HTTP uses `/api/inter-agent/runs/<run_id>/participants`; CLI uses `inter-agent.participants.spawn`; MCP uses `inter_agent_participant_spawn`. All three must route through the policy-aware service, require run creator/owner or admin authority for mutations, and must not call `create_child_runtime_session` with parent-copied or user-payload authority. Public run/spawn payloads may name topology, participant id, child session id, owner, and an agent type reference under policy; they must not materialize prompt text, skill ids, skill catalog, source app, provider selection, agent snapshots, or runtime operation grants from caller-controlled data. Chat HTTP run creation may include an `agent_snapshot` request envelope only when the root session source app is Chat's selected agent provider. The core must replace that envelope before spec parsing by invoking Chat's selected `agent.catalog` and `agent.prompt-materializer` dependency backend surfaces, validating the agent type id, provider id, disabled state, returned definition consistency, and a server-authoritative skill catalog from either the provider/materializer response or the provider's selected `runtime-skills` dependency. A client-supplied `skill_catalog_app_id` may constrain the materialized value but must never be the fallback authority. If the root session prompt contains the structured Chat active-app context block, the core may preserve it only after re-resolving the active app through the visible app registry and reconstructing the block from registry metadata. Source app for a public inter-agent run is derived from the root runtime session, not from the caller payload. A non-operator caller may attach a run to a root runtime session only when they own that root, are an admin, or hold an explicit platform-minted `inter_agent_root` grant; workspace membership alone is not sufficient.

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
- `manager_tools` must send child workers a delegated task frame, not the raw user prompt alone; workers must be told to complete the assigned work and not role-play the orchestrator or re-delegate
- `sequential` passes declared output from one participant into the next participant input
- `concurrent` fans out participants under `max_concurrent_participants` and then aggregates through the root orchestrator or declared aggregator participant
- participant/task/artifact/summary/run lifecycle events are persisted as normalized `inter_agent` events
- artifact refs and partial output must be persisted before a participant failure is recorded
- root runtime projection uses non-terminal runtime step updates for selected plan/status summaries and `runtime.output.final` for the final answer when a root turn projection exists
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

## F5 Graph Mode Policy

The initial graph mode remains inside the Chat app for the MVP. It is an operational view over core-owned inter-agent records, not a new Fleet or Orchestrations app.

Core additions for F5:

- `WS /ws/inter-agent/runs/<run_id>` streams an authorized graph snapshot, bounded replay, history pages, live event frames, and heartbeats.
- The WebSocket accepts `visibility_plane`, `last_event_id`, and `initial_event_limit` query parameters. The served plane is capped server-side by caller authority and by the run's `visibility_level`.
- Client history frames use `inter_agent.history.before` with `before_event_id` and `limit`; the server returns a bounded page from the same store paging path as HTTP.
- `GET /api/inter-agent/runs/<run_id>/artifacts` projects artifact records from authorized `inter_agent.artifact.created` events and supports the same paging and visibility parameters as event replay.
- `GET /api/inter-agent/runs/<run_id>/participants/<participant_id>/transcript` serves the product-facing participant transcript from the inter-agent projection and, when present, safe runtime turn input/output. It must not expose hidden child runtime session ids, raw runtime endpoints, debug payloads, or uncapped detail/debug events. The effective event plane is capped server-side by caller authority and by the run's `visibility_level`.

Chat Agent nodes view renders graph nodes, edges, participant transcripts, approvals, empty/loading/error states, and essential pause/resume/stop controls. It must not make timeline, JSON inspector, sequence number, visibility plane, debug payload, or Summary/Detail/Debug tabs part of the primary product-facing UX. Pause uses `POST /api/inter-agent/runs/<run_id>/interrupt`; stop uses `POST /api/inter-agent/runs/<run_id>/close` with `terminal_status=cancelled`; resume uses `POST /api/inter-agent/runs/<run_id>/resume`. Chat-created multi-agent runs request `visibility_level=detail` so Agent nodes can show tasks, declared participant input, final output, participant state, and artifacts by default without exposing debug-plane data.

If the visible root runtime turn for a Chat-projected inter-agent run is interrupted through the generic runtime turn API, the core must close the linked inter-agent run as `cancelled`, clean up active hidden child participant sessions through the inter-agent close path, and avoid any later `cancelled -> completed` root turn transition.

The F5 WebSocket may poll the inter-agent event store for the MVP. A dedicated inter-agent event bus can be introduced later if run event volume requires fanout semantics comparable to runtime session events.

## F7 Group Chat Policy

F7 starts with `group_chat` and does not promote `handoff` or `magentic_like` as product modes.

The `group_chat` MVP remains Maverick-native. Chat and the HTTP inter-agent API use the existing `InterAgentRun`, participants, edges, events, budget ledger, approvals, retention, replay, hidden participant sessions, and Agent nodes UI. MAF remains source-backed evaluation/reference material and does not own product runtime state.

The Chat composer shows `Group chat` only when `VITE_MAVERICK_FEATURE_GROUP_CHAT=1`. Public HTTP/CLI/MCP creation and execution of `mode="group_chat"` require `MAVERICK_FEATURE_GROUP_CHAT=1`; public creation of `handoff` and `magentic_like` is rejected as not product-facing. Chat-created group chat runs request `visibility_level=detail`, declare a non-orchestrator aggregator participant, set bounded one-round budget defaults, and rely on the existing Agent nodes view for run status, participant outputs, cancel/stop, replay, and history.

The F7.1 executor semantics are intentionally narrow: one bounded shared-context round over declared group participants, with an explicit aggregator participant for final answer projection. Checkpointing, replay-fork, graph super-steps, task writes, native conditional routing, raw adapter payload UI, and MAF-owned sessions remain non-goals.

## Gate

No later phase may bypass the inter-agent service when creating real child runtime sessions. Hidden thread visibility and raw runtime access rejection must remain covered by runtime-thread, runtime HTTP, WebSocket, cleanup, and inter-agent service/API tests. Adapter phases must map back into the same run, participant, budget, artifact, and event contracts rather than owning Maverick session or secret state.
