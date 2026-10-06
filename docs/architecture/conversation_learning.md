# Conversation Learning

Conversation learning is owned by Chat, administered from Settings, and writes
approved knowledge through the selected `memory.graph` backend provider. Core
owns only generic terminal notifications and bounded background generation.

Terminal Chat callbacks enqueue evidence; they never run inference. Queued user
messages cancel an in-flight pass and postpone its next attempt. Core asks Chat
to revalidate the durable claim immediately before inference, closing the
claim-to-dispatch race with pause or cancellation. The worker waits for the configured idle delay and
for linked orchestration to finish. Only new completed exchanges are consumed;
failed exchanges are available as process evidence, never proof of success.

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
Improvement proposals always require review and never modify code or skills.

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
Thread cleanup removes pending inputs and cancels their jobs; already approved
Memory knowledge retains its explicit source provenance and can be undone.
