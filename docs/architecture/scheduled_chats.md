# Scheduled chats

Chat owns scheduled conversations under `data/chat/scheduled.sqlite`. Core remains
the owner of runtime sessions, turns, admission and cancellation. The existing
Chat `background_tick`, `backend_recovery` and `runtime_event` hooks drive work
without a browser; no client timer executes an agent.

A scheduled chat contains a bounded, acyclic graph of skill blocks and an IANA
timezone schedule. React Flow edits this graph. Edges are prerequisites: a block
can start only after every incoming block has been confirmed. Independent ready
blocks run in parallel, with a bounded workspace concurrency. Each successful
turn stops at a checkpoint; confirming it permits downstream work. Failed or
cancelled work never satisfies an edge. A recurrence starts a fresh graph run
only when the previous run has ended; missed occurrences coalesce rather than
creating an unbounded backlog. Pausing stops new dispatches and interrupts active
block turns. Resuming preserves completed checkpoints.

Runs snapshot their graph. Editing is rejected while a run is open, so a UI or
agent cannot invalidate prerequisites underneath executing work. Configuration
writes require an expected revision. SQLite transactions serialize claims and
persist runtime request payloads before dispatch. Every dispatch uses Core's
durable stream idempotency key. Recovery replays the exact request, reconciles
Core-provided request states and deduplicates terminal events. Ambiguous launch
state is never retried under a fresh key. Known failed blocks require an explicit
retry. Deleted schedules are tombstoned until in-flight callbacks are fenced.
CLI/MCP operations enqueue durable outbox records; hosted background hooks admit
those turns with the full platform context and the persisted initiating actor.
Mounted backend actions can dispatch immediately through the same outbox.

The bottom composer belongs to the schedule's management conversation. It uses
the normal Chat composer and transcript, and submits app runtime requests with
a bounded graph context and a stable scheduled-chat reference. AI graph creation
and edits use the same validated `chat_scheduled` MCP/CLI operations as manual
editing. Block instructions are injected into each worker turn; optional stable
workspace skill ids use explicit runtime skill activation. Worker conversations
remain inspectable through the authorized Core transcript surface.

Scheduled-chat references use `scheduled_chat`, `/app/chat/scheduled/<id>`, and
the existing isolated-frame reference drag broker. Reference resolution and all
scheduled operations are scoped to the trusted actor and the owning workspace.
Central Shell notifications report checkpoints, failures and completion, with
Chat-owned deduplication and per-user receipts. The UI is English, uses native
Chat glass tokens and lazy-loads the graph editor.
