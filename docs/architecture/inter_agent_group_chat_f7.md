# Inter-Agent Group Chat F7 ADR

Date: 2026-06-22
Status: Accepted for F7.0/F7.1 MVP

## Decision

`group_chat` is the first advanced inter-agent mode promoted to a product-facing
Maverick mode.

The mode is not default-on. Product exposure requires both:

- server/public-surface flag: `MAVERICK_FEATURE_GROUP_CHAT=1`
- Chat frontend build flag: `VITE_MAVERICK_FEATURE_GROUP_CHAT=1`

When either flag is absent, Chat must not show the composer option and the HTTP
inter-agent API plus core CLI/MCP public inter-agent surfaces must reject
`group_chat` run creation or execution.

`handoff` and `magentic_like` remain adapter/evaluation or schema-only modes.
They are not promoted as F7 product modes.

## Ownership Boundary

Maverick remains the owner of:

- `InterAgentRun`, participant, edge, event, artifact, approval, and budget
  records
- root and hidden participant runtime sessions
- provider selection and model access
- secret resolution and grant policy
- workspace isolation
- retention and replay
- cancel, pause, resume, and close operations
- Chat UI and product-facing payload shape

The Microsoft Agent Framework adapter remains source-backed evaluation and
reference material. It does not own runtime sessions, product run state,
provider access, secrets, replay, retention, budget, approvals, or UI payloads.

## Product Surface

F7.1 exposes `group_chat` through Chat as a gated composer mode named
`Group chat`. Chat-created runs:

- call `POST /api/inter-agent/runs` with `mode="group_chat"`
- request `visibility_level="detail"` so Agent nodes can show safe participant
  outputs and replayable run history
- declare a bounded participant graph with root orchestrator, group participants,
  and an aggregator participant for final answer projection
- execute through `POST /api/inter-agent/runs/<run_id>/execute` with async root
  transcript projection
- use existing Agent nodes controls for status, participant transcript,
  artifacts, approvals, pause/resume, stop/cancel, WebSocket replay, and older
  history pages

The core HTTP API and core CLI/MCP public inter-agent surfaces allow
`group_chat` only when `MAVERICK_FEATURE_GROUP_CHAT=1`. The existing
product-facing modes `manager_tools`, `sequential`, and `concurrent` remain
available. Public creation of `handoff` and `magentic_like` is rejected because
those modes are not product-facing.

## MVP Runtime Semantics

The F7.1 native executor runs `group_chat` as one bounded shared-context round
over the declared non-orchestrator participants. Each participant receives:

- the shared user request
- its participant-specific focus
- safe summaries of earlier participant outputs in the same round

The existing budget ledger reserves participant slots and turns. Chat sets
`max_rounds=1`, `max_turns_per_participant=1`, and `max_total_turns` equal to
the number of group participants for the MVP. Later multi-round behavior
requires a separate graph/checkpoint decision.

## Requirements

- Budget: all participant turns go through existing budget reservations and
  ledger enforcement.
- Cancel: Chat uses existing Agent nodes stop, which closes the inter-agent run
  as `cancelled` and cleans up hidden participant sessions through Maverick.
- Replay/history: all user-facing state comes from `InterAgentEventRecord`,
  event pages, and `WS /ws/inter-agent/runs/<run_id>`.
- Visibility: Chat-created runs use detail visibility for safe participant
  outputs. Debug payloads, raw adapter state, and hidden runtime internals stay
  out of the product UI.
- Approval: existing inter-agent approval records and resolution APIs remain
  the only product approval path.
- Retention: existing summary/detail/debug retention policy remains the source
  of truth for replayable events.

## Non-Goals

- No MAF-owned sessions or product runtime state.
- No checkpoint, replay-fork, task-write, graph super-step, or native graph
  reducer semantics.
- No `handoff` product mode.
- No `magentic_like` product mode.
- No raw adapter payload UI.
- No manager debug console or raw hidden runtime-session links.
