# Inter-Agent Runtime Invariants

Date: 2026-06-15
Status: Accepted for F0

## Purpose

This ADR fixes the runtime invariants required before Maverick can create real multi-agent child sessions.

It is intentionally limited to names, visibility, legacy compatibility, and initial policy defaults. It does not introduce an executor, participant spawn API, graph mode, adapter, or real child-session workflow.

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

## Initial Policy Defaults

Budget policy starts fail-closed and run-scoped:

- non-`single_agent` runs must declare max participants and max concurrent participants
- spawn, handoff, and fan-out require reservation before work starts
- reservations and releases must be idempotent
- turn, tool-call, estimated-token, estimated-cost, idle, and stall limits are enforced by the core
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

This keeps the primary Chat transcript as one visible conversation while allowing future participant sessions to execute without appearing as standalone chats.

## Child Session Helper Boundary

The internal `create_child_runtime_session` helper is not the public multi-agent spawn API.

It may reuse only the parent session's resolved workspace boundary, workdir, execution mode, and runtime-session parent linkage. Prompt materialization, skill ids, skill catalog, source app, owner, creator, and operation grants must be explicit inputs produced by core policy, an authorized app snapshot, or a later `ParticipantSpec` materialization step. The helper defaults those authority-bearing fields to empty values and must not clone them from the parent session.

## Inventory For F2

F0 models the visibility boundary and blocks thread creation for hidden sessions. F2 must apply server-side visibility policy to raw runtime session access paths before real participant sessions are exposed outside tests:

- `GET /api/runtime/sessions`
- `GET /api/runtime/sessions/<session_id>`
- `GET /api/runtime/sessions/<session_id>/events`
- `GET /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/turns`
- `WS /ws/runtime/sessions/<session_id>`
- CLI and MCP runtime status surfaces

Until that F2 policy exists, no public core, Chat, Agents, or app-owned surface may create real `inter_agent_participant` sessions.

## Gate

No later phase may create real child runtime sessions outside tests until hidden thread visibility is modeled, documented, and covered by runtime-thread and API tests.
