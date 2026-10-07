# Conversation Learning

Conversation learning is owned by Chat, administered from Settings, and writes
approved knowledge through the selected `memory.graph` backend provider. Core
owns generic runtime requests, terminal notifications, stream reconciliation and bounded background generation.

Terminal Chat callbacks enqueue evidence; they never run inference. Queued user
messages cancel an in-flight pass and postpone its next attempt. Core asks Chat
to revalidate the durable claim immediately before inference, closing the
claim-to-dispatch race with pause or cancellation. The worker waits for the configured idle delay and
for linked orchestration to finish. The quiet period schedules review, not task
closure. New exchanges advance the cursor; bounded previous exchanges and the
persisted episode assessment supply context. Failed exchanges are process
evidence, never proof of successful completion or confirmed knowledge.

`background_generation_requests` is a generic app-result capability, restricted
to apps declaring runtime session creation. Requests supply a bounded prompt,
JSON schema, timeout, model selection and callback. Core runs isolated, tool-free
Codex inference or the explicitly selected configured `fast_model` text provider.
Provider credentials stay in Core. Background generation is internal work, not a
new user chat, and its transcript is inspected in the owning app's run history.

One installation-wide exclusive generation slot is held across inference,
validation, callback and downstream app writes. The operating file lock is
inherited by the native process so a backend crash cannot admit overlapping
inference while that process survives. Shutdown/cancellation terminate the
managed process group. Chat additionally uses transactional attempt tokens:
stale, cancelled or replayed callbacks cannot overwrite current analysis.
Backend recovery replays up to 100 recent source-owned terminal turns (ten per chat), filtered against the latest enable time, and retries interrupted jobs with a new token. It does not launch inference until the backend lifecycle owner is ready. A busy slot defers
work, without consuming the daily reservation or losing the queued input.

Chat persists settings, bounded evidence, durable jobs, candidates, proposals,
review decisions and audit records under `data/chat/learning.sqlite`. Memory
continues to own graph nodes, immutable sources, citations and compilation.
Approved facts enter through idempotent source ingestion with stable source
keys. Ambiguous facts and conflicts require review; automatic mode applies only
to explicit, strongly supported user statements with no existing-memory match.
Improvement analysis only produces proposals. Accepting a proposal authorizes a normal Chat agent to implement that reviewed ticket.

Default rollout is disabled, review mode, a two-minute delay, one analysis at a
time, bounded context/output, runtime timeout and daily token reservations.
Native token totals may exceed a reservation; observed consumption is reconciled
and blocks subsequent work at the daily limit. Reservations are conservative
when provider usage is unavailable. Each inference is one finite pass and may
produce empty result lists. Derived analyses never enter the input queue.

Settings exposes enable/pause, channels, model, delay, exclusions, budgets,
review/automatic mode, queue controls, manual analysis, editable candidates,
Memory approve/reject/undo, proposal lifecycle and run transcripts. Browsing and
mutating learning state requires platform or workspace admin authority.
Thread cleanup removes pending inputs and cancels their jobs. Unsaved candidates,
including accepted tickets, lose the deleted source's quotes and analysis links.
Candidates without remaining evidence are rejected before launch and their queued
tickets are cancelled. Remaining evidence requires reassessment; admitted work receives a
stale review and cannot commit Memory. Already saved Memory knowledge retains
its explicit source provenance and can be undone.

## Review hardening (2026-10-06)

Queue selection skips occupied chats and chats still inside their idle window,
then claims the oldest ready chat in the same transaction. An occupied oldest
chat cannot monopolize the serial worker. The installation-wide generation
lock and request-token fences remain the authority for single-pass execution.

Saving exclusions immediately cancels a matching in-flight pass and clears its
claim. Turning both output channels off also cancels the pass; disabling one
channel filters that channel out when an already-running result is validated.
Late callbacks still reconcile their known attempt's observed usage, using a
monotonic maximum, before result fencing. They cannot create candidates or
move the conversation cursor after cancellation.

The administrative read model includes exact pending/queue/failure counts,
independent of bounded result history, and short redacted evidence labels for
captured chats. Results awaiting review precede archived items in the bounded
list. A budget-blocked job records a visible waiting reason; its first transition
publishes an invalidation without producing an event on every idle tick.
Settings presents status, allowance, output channels and
review results first, with model/timing, usage/retention and exclusions in
collapsible sections. Refresh preserves local settings/candidate drafts,
selection and focus; discarding edits is explicit. Partial pause/resume actions
leave other drafts intact. Read epochs prevent a pre-save response from
replacing newer saved state. Live invalidations use the SDK shell event stream
for isolated app frames, and evidence links target the injected shell origin.


## Accepted tickets and work chats (2026-10-07)

Memory and Improvements use the same Settings Kanban with open/all/closed filters,
search, categories, a list alternative, evidence and work-chat links. Dragging
issues the same authoritative commands as keyboard-accessible action buttons.
Users cannot fabricate a running state. Improvements reach review after a normal
agent turn and require explicit confirmation to become implemented. Memory
requires a provider-confirmed save; a completed turn alone cannot mark it saved.

Acceptance persists an implementation ticket in learning SQLite schema version 3,
with source-analysis associations and deduplicated runtime event receipts. Generic
runtime requests use the accepting user and normal workspace agentic profile.
Memory runs one work chat at a time, independently of improvement capacity.
Improvements run four chats concurrently by default; Settings allows one to eight.
Reducing the limit leaves admitted turns running and blocks further claims until
capacity is available. Accepted tickets use normal Chat usage. Analysis pause and
its token allowance continue to govern analysis alone.

Chat atomically maintains ordinary Memory and Improvements projects, identified
by internal purpose markers that survive renaming. Both session and thread use
the relevant project ID. Creating them publishes the usual projects invalidation.
Previously accepted proposals require an explicit Start and are not automatically
launched by migration.

The initial launch has an immutable request and stable stream idempotency key.
Concurrent clicks/ticks cannot create another initial conversation. Retry reuses
the chat with a new turn; an unconfirmed launch replays its original key. Stops
hold capacity until the runtime turn terminates. Deleting a work chat cancels its
ticket. Generic request IDs on source runtime events and source-owned stream
snapshots recover lost handoffs before evidence replay. Recovery reconciles state
and defers launches to normal lifecycle ticks. Generated work chats and their
manual follow-ups are excluded from analysis.
If the running Core host has not loaded the new deferred-launch contract, the
app leaves accepted tickets queued and displays launch readiness. A host reload
activates the contract; accepting tickets during the update cannot launch them
as an unowned system actor.

Briefs contain approved text, verification criteria, exact quotes, analysis IDs
and identifiers/links for all source chats. Structured runtime references are
bounded; all identifiers remain in the brief. Agents read the originals and
verify current state before acting. Parallel fixes must preserve concurrent work.

Memory acceptance pins the provider and explicitly selected existing node or
separate-fact destination. The agent verifies sources, then uses the app-owned
chat_learning_memory MCP tool. It accepts candidate ID and inspect/commit only,
checks the Core-stamped caller session against the assigned work chat, and sends
the existing idempotent ingestion request through learning-memory. Arbitrary
content, providers and destinations are not accepted. The agent inspects the save
receipt before reporting success. Memory's callback owns node/revision truth and
guarded undo. A late confirmed save repairs a failed/stopped projection without
admitting another active Memory chat. The existing explicit-fact automatic saving
mode remains a direct provider operation.

## Episode and relevance policy (2026-10-07)

Policy version 2 requires an explicit episode assessment: completed, ongoing,
blocked or uncertain, with summary, open work and exact quoted evidence. A
completed assessment needs new completed evidence of the outcome and no open
work. Runtime turn completion and idle duration do not establish this outcome.
Only completed episodes may publish candidates. Other assessments persist
internal context without producing tickets or Memory candidates. Classification
is semantic model judgment constrained by this evidence contract, not a timer
or a prediction of the user's future turns. At most three candidates per channel
are accepted; empty outputs are expected.

The reviewer receives up to eight bounded prior exchanges, the last episode
summary, and up to eight other captured chats with active user requests or
persisted ongoing, blocked or uncertain episodes. Each includes a bounded episode
summary and open work, so unfinished work remains visible between turns. Completed
idle episodes are omitted. Bounded existing items include user-discarded proposals.
Thread and project exclusions apply before selecting other chats. Context and
output remain within the configured bounds.
The reviewer is tool-free: evidence includes terminal text and overall/queue
duration, not verified per-tool error/timing traces. It must distinguish a
reported symptom from a proposed diagnosis and cannot assign total turn time
to a particular tool.

Improvements require Maverick scope, a specific capability/reliability/tool/
performance/workflow problem, an explanation of value for other tasks, and a
verification criterion. Task-local requests, work already requested, in
progress, resolved or duplicated are filtered. Reconciliations cite current
evidence and can retire pending proposals and cancel queued implementations;
they cannot stop an already admitted agent or fabricate a completed fix.
Admitted work gets a review warning when appropriate. New source turns mark
proposals stale. Accepted tickets wait for a current completed reassessment
before launch; waiting tickets do not occupy capacity or starve ready tickets.
Ticket polling ensures a claim for new evidence without moving an existing
deadline, duplicating an in-flight review, or retrying cancelled/failed evidence.
New terminal evidence still resets the idle window; manual analysis can bring
the queued review forward. All evidence and analysis source chats must exist
with matching reviewed revisions before launch or Memory commit.
In-flight results superseded by newer or unconsumed evidence cannot publish
new candidates. Retired content cannot be recreated by changing its model key.

Memory requires confirmed, durable knowledge useful beyond the task: people,
organizations, relationships, sourced discoveries, occurred events, important
business decisions or enduring personal preferences. Development requirements,
UI choices, temporary progress and implementation instructions are excluded,
including a conservative guard against misclassified toggle/layout requests.
Completed assistant research is eligible only with cited URLs or app references
present in its supplied source exchange. A bare claim of verification is
insufficient. The work agent reads the cited sources before saving. Direct
automatic ingestion requires exclusively user-role evidence and a verbatim user
statement. Assistant or mixed-role research requires approval and the verifying
work agent even when the reviewer sets `explicit=true`. Citations,
knowledge type, confirmation and review time travel through Memory source
ingestion. A changed source blocks commit as well as automatic saving.

SQLite schema 3 adds app-owned episode/current-request context while preserving
existing records. The current policy version is stored with each candidate;
older candidates require fresh review before approval. Core remains unchanged
and app-agnostic; app entrypoints load the new review contract on invocation.

The Chat CLI exposes administrator-only `learning.read` and
`learning.discard_all`. Discard atomically dismisses all unsaved candidates,
requests stops for active implementation turns, cancels outstanding analysis
claims and advances captured evidence cursors. Delayed callbacks cannot restore
the discarded results. Historical records and dismissal reasons remain visible;
already saved Memory knowledge is managed through its guarded undo/provider
surfaces. Provider writes already in progress must settle before bulk discard.
The next captured evidence starts a new review under the current criteria.
