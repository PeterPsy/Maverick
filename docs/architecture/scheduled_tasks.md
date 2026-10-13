# Scheduled tasks

Chat owns scheduled tasks under `data/chat/scheduled.sqlite`. Core remains
the owner of runtime sessions, turns, admission and cancellation. The existing
Chat `background_tick`, `backend_recovery` and `runtime_event` hooks drive work
without a browser; no client timer executes an agent.

A scheduled task contains a bounded, acyclic graph of skill blocks and an IANA
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
retry with a new dispatch key, including definitive admission failures without a
turn. An explicitly retried ambiguous stopped launch retains its original key
and payload. Pausing, cancelling or deleting also cancels unsubmitted outbox
records. Recovery checks the persisted task/run/step fence before replaying any
launch; a late launch callback interrupts the bound turn through Core before
worker activation. Deleted schedules are tombstoned until in-flight callbacks
are fenced.
CLI/MCP operations enqueue durable outbox records; hosted background hooks admit
those turns with the full platform context and the persisted initiating actor.
Mounted backend actions can dispatch immediately through the same outbox.

Successful recovery waits for the persisted final result before exposing a
checkpoint. Core's source-owned request states include bounded terminal output
when the terminal event exists; a missing output field is distinct from an
authoritatively empty result. Delayed terminal callbacks use the same rule and
cannot launch a successor with a placeholder result.

The bottom composer belongs to the schedule's management conversation. It uses
the normal Chat composer and transcript. The management conversation is
initialized with the task goal and a stable scheduled-task reference; graph edits
read the latest state through the app's operations. AI graph creation
and edits use the same validated `chat_scheduled` MCP/CLI operations as manual
editing. Block instructions are injected into each worker turn; optional stable
workspace skill ids use explicit runtime skill activation. Worker conversations
remain inspectable through the authorized Core transcript surface.
The block inspector follows refreshed skill selections while preserving the
user's in-progress comma-separated input when its parsed selection is unchanged.

Scheduled-task references use `scheduled_chat`, `/app/chat/scheduled/<id>`, and
the existing isolated-frame reference drag broker. Reference resolution and all
scheduled operations are scoped to the trusted actor and the owning workspace.
Central Shell notifications report checkpoints, failures and completion, with
Chat-owned deduplication and per-user receipts. The UI is English, uses native
Chat glass tokens and lazy-loads the graph editor.

The sidebar presents Chats and Scheduled tasks as separate sibling sections,
without container backgrounds, borders or shadows; spacing separates the lists.
Primary and footer widget canvases are transparent from first paint in both
themes, allowing the Shell sidebar surface to show through. Sections add no
container insets; the host owns outer spacing and the widget retains clearance
for the overlaid header and footer.
Both use the same view selector, search and action toolbar. Task filters and
search are local to the task block; the chat search shortcut remains scoped to
Chats. Each list scrolls independently, keeping both toolbars available. Task
creation opens `/app/chat/scheduled/create/new`, which cannot collide with a
single-segment task id. A task owns a management chat; the chat is its composer
and transcript, while the task is the scheduled graph and its checkpoints.
The existing `scheduled_chat` reference discriminator and `scheduled-chats`
data resource identify this Chat-owned persisted entity; visible product copy
and agent instructions call it a Scheduled task.
