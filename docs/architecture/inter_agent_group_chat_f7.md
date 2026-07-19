# Inter-Agent Group Chat F7 ADR

Date: 2026-07-19
Status: Superseded as a Chat execution design

The static Chat topology and root-transcript behavior in the original F7
decision are superseded by
[Generalist And Multi-Agent Orchestration](inter_agent_orchestration_redesign.md).
The feature flags and low-level executor constraints remain applicable.

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

Chat exposes `Group chat` as a gated orchestration policy. It first submits the
message to the independent generalist, then calls
`POST /api/inter-agent/orchestrations` with `policy="group_chat"`, the root
session, the accepted source turn, and an idempotency key. The request contains
no participant graph, executor input, or budget. The core starts an
orchestrator-only board and materializes the group participants and edges from
the orchestrator's validated plan. Agent nodes uses its existing transcript,
artifact, approval, pause/resume, stop/cancel, WebSocket replay, and older
history surfaces. Nothing from that board is projected onto the root Chat
transcript.

The core HTTP API and core CLI/MCP public inter-agent surfaces allow
`group_chat` only when `MAVERICK_FEATURE_GROUP_CHAT=1`. The existing
product-facing modes `manager_tools`, `sequential`, and `concurrent` remain
available. Public creation of `handoff` and `magentic_like` is rejected because
those modes are not product-facing.

## Legacy Low-Level Runtime Semantics

The retained low-level native executor runs `group_chat` as one bounded shared-context round
over the declared non-orchestrator participants. Each participant receives:

- the shared user request
- its participant-specific focus
- safe summaries of earlier participant outputs in the same round

The existing budget ledger reserves participant slots and turns. This executor
is not the Chat product path; product group orchestration uses dynamic budgets,
dependency scheduling, and the bounded quality-review loop defined by the
superseding ADR.

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
