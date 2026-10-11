# Memory retrieval and navigation

Memory owns retrieval, evidence evaluation, graph traversal and compilation.
Platform CLI/MCP/backend transports call the same app service; Core owns admission
and the background hook lifecycle. The UI uses those backend actions, without a
second retrieval implementation. Existing Storage integrity and ownership rules
continue to apply.

## Retrieval path

Agents start with `memory_context`, explore known IDs with `memory_explore`, then
request selective `memory_inspect_node` evidence or integrity-checked
`memory_fetch_chunks`. `memory_search` and `memory_get_nodes` default to cards.
This supports a short context → connections → evidence path without making a
complete audit inspection the cost of following an edge.

`retrieval_cards.py` projects bounded titles/summaries and batches indexed evidence,
source and compilation indicators. It never reads archived source files, node
bodies in full, or revision snapshots. Conversation provenance retains at most
three session/turn/role references; original chat quotes are not copied into cards.

`search_candidates.py` ranks FTS node, wiki, claim and current-source channels
before paging. Stable node/person/project IDs, metadata aliases and active app
entity references provide exact identity matches. Wiki search uses the same FTS
ranking and scope rules. Source search retains source-specific locators and hashes.

Project/person IDs are exact filters. `include_unscoped` explicitly allows general
preferences alongside a project/person. `as_of` defaults to today's date and
filters inclusive `valid_from`/`valid_until`; `include_expired` opts out. Temporal
filtering does not reconstruct a replaced fact: use revision headers and explicit
revision content for that task.

## Paging and budgets

Paged retrieval reads a page plus one result to determine continuation. Cursors
bind the request and an indexed read revision; changed requests or intervening
changes return an explicit stale-cursor error. A caller restarts the request and
deduplicates stable IDs. Each request uses a read transaction; no search writes the
shared graph view or audit unless the existing access-event option is explicit.

Responses distinguish `has_more`, `next_cursor`, `omitted_for_budget`, and
`stop_reason` (`limit`, `budget`, `end`). Default JSON budget is 9,500 UTF-8 bytes;
callers may request 2,000–64,000. An individual result that cannot fit raises a
validation error rather than silently returning an empty continuing page.

Context additionally distinguishes `retrieval_has_more` / `search_next_cursor`
from `budget_omitted_node_ids`. An exact candidate count is only asserted for an
exhausted first page; otherwise the total is null. Up to two critical edges and
their outside neighbors are considered even when text hits fill `limit`. One
contradiction and one supersession receive priority when both exist. These
neighbors precede text results during byte compaction. `critical_has_more` directs
the caller to explore remaining critical relationships, including when all of
them have the same kind. Each kind reads an additional edge to detect overflow.

Context and `search` with `detail=evidence` validate source-channel matches against
integrity-checked stored passages. A failed or missing passage removes that match
channel; a source-only candidate is omitted. Valid node/identity/wiki/claim matches
remain available. Continuation advances over the original indexed positions even
when an entire page is rejected, and byte limits include the resulting cursor.
Card search remains an inexpensive indexed discovery surface.

`source_matches.py` reads eight ranked passage candidates per selected node in
each batched query, retaining at most three integrity/query-checked matches per
node. A long source cannot consume another node's verification sample. Streams
with no valid passages continue past damaged or missing candidates until a
verified sample or exhaustion; absence in one sample is never treated as invalid
evidence. A sample containing any valid passage stops further scanning for that
node even if the sample contains fewer than three passages. Body reads are cached
across shared chunks within the request. Response size is bounded; verification
has no fixed time limit. A source without intact matches can require scanning its
remaining indexed passages before rejection is justified.

`exploration.py` follows incoming/outgoing/both edges, optional kinds and scope,
from one to five seeds. Default depth is one, explicit maximum two. Recursive
visitation deduplicates `(node, hop)`, derives shortest node distances, and pages
edges by their ID; parallel kinds and cycles retain distinct edges. `hop` follows
the requested direction. Endpoint cards include reasons, revisions and uncertainty.
`visited_node_ids` describes this response's endpoint set, not an opaque mutable
session stored by the backend.

## Detail levels and evidence

`node_reads.py` provides cards, content, evidence, sources and history separately.
Batch reads support up to twenty cards. Content pages by character offsets while
enforcing bytes; history returns revision headers and loads a selected revision's
body only on request. The legacy complete inspection remains available through
explicit `detail=full`, intentionally unbudgeted for audit callers.

Evidence pages expose claims, supporting/conflicting/related citations and stable
Storage links. A claim with more citations supplies a `claim_id` detail request.
Verification aggregates all current claims, including those outside the page.
Source passages remain accessible while compilation is pending. Original passage
reads continue to verify stored SHA integrity before returning text.

Card state is explicitly an **indexed observation**. Selective evidence and full
inspection observe live source currency. Confidence, user confirmation, supporting
verification and inferred relationships remain different fields. Reading a card
does not assert that its original document has just been re-read.

Cards include `state_revision`, a bounded indexed-state fingerprint covering the
fact, compiled page, queue indicators, evidence counts, active source updates and
attached external references, including references not yet compiled into sources.
Reference count/latest update are batched in the existing source-state query;
adding a reference also invalidates retrieval cursors through the read revision.
It can change without editing the fact's `updated_at`/`revision`. The inspector
invalidates cached sections and pending reads on this state change while keeping
the selected tab. Within one state revision, live verification/source/freshness
observations survive later content/source/history reads that supply indexed cards.
Evidence previews are reset with the state revision too. The fingerprint does not
claim to observe external files that have changed outside Memory's index.

## Deferred compilation

Memory declares `background_tick` and `backend_recovery` hooks. The platform runs
them independently of visible UI state; the frontend no longer supplies a polling
worker. Memory's maintenance tick uses a cross-process OS lock, at most three
compile/lint jobs, and a two-second soft budget checked between jobs. One job may
exceed that budget. Suggested next due time is fifteen seconds with backlog,
sixty when idle; platform execution policy remains authoritative.

Existing job deduplication, retries and expired lease recovery remain in place.
Claiming work also excludes a live compile/lint lease for the same node, including
explicit job runners. Storage reindexing remains an explicit Storage operation;
the worker does not restore removed sources or invent remote access. Chat Learning
continues to compile its saved fact immediately.

## UI and context references

The UI starts with thirty cards and retains at most forty visible nodes. A selected
node, including one opened from Chat, is merged into the graph with its explored
neighborhood. Connections retain edge IDs, paged continuation and back navigation.
Graph references update synchronously with the state change so a navigation that
continues before React renders cannot replace a freshly loaded context.
Content, Connections, Sources and History load on demand. Correction is enabled
only after the complete current body has loaded.

Cytoscape is the only graph engine, dynamically imported in the graph frame.
App-native controls and vector icons remain owned by Memory. Bezier edges separate
parallel relationships, arrows expose direction, and edge selection exposes the
reason. Initial CoSE layout includes labels; incremental placement locks existing
nodes. Selection brings the node into view at a readable minimum zoom. A native
keyboard list supports navigation independent of canvas hit testing.

Context responses return `view.node_ids` and `view.snapshot_id`. Shell navigation
parameters `context_node_ids` (JSON string) and `context_snapshot_id` reopen those
references in a local frontend view. They do not overwrite workspace view state.
Reopening retrieves current cards: this is an identifiable reference set, not a
persisted historical snapshot. Preserve the original response and node revisions
when historical evidence matters.

See [validation and measured costs](../development/memory_navigation_validation_2026-10-11.md).
