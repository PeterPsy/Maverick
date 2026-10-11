# Memory navigation validation — 2026-10-11

## Implemented behavior

- `memory_explore`: read-only, directional, kind/scope-filtered, bounded one/two-hop
  traversal, paged by stable edge identity with compact endpoint cards.
- Correct continuation for context, search, wiki, source, batch and detail reads;
  byte omissions are separate from additional search candidates.
- Context reserves critical contradictions/supersessions even when textual hits
  fill the requested limit, preserving reasons and inference uncertainty.
- Platform background/recovery hooks progress deferred compile/lint work with
  locking, bounded ticks, existing deduplication, retries and lease recovery.
- Lightweight maps, batch cards and selective content/evidence/sources/history;
  original passage SHA verification remains mandatory.
- Shared FTS/scope/validity/identity rules and documented, tested MCP outputs.
- One lazy Cytoscape engine, parallel directed edges, native keyboard navigation,
  selected neighborhoods, paged connections, back navigation and lazy panel tabs.
  Conversation reference views do not overwrite workspace view state.

Architecture: [Memory retrieval and navigation](../architecture/memory_navigation_architecture.md).

## Follow-up review of `abfda5bf`

The review reproduced four defects on temporary data and DOM fixtures:

1. Three critical edges of one kind returned two edges with
   `critical_has_more=false`. An additional edge per kind now detects overflow;
   the existing two-edge reservation and kind priority are preserved.
2. A source-only hit survived a missing/corrupted stored passage, returning an
   unrelated fact with reason `Matches a current source passage`. Context and
   evidence search now remove failed source match channels, retaining valid other
   channels. Rejected indexed positions still advance cursors; tests cover empty
   continuing pages and byte-budget truncation without duplicate/lost valid IDs.
3. Replacing evidence changed `verified` to `conflict` without changing the fact's
   timestamp, so the open inspector kept old quotes and verification. Compact
   `state_revision` fingerprints now invalidate sections, requests and previews
   when compilation/evidence/source/queue state changes; the current tab is kept.
4. Loading the source list after live evidence could overwrite `unverified/stale`
   with indexed `verified/current`. Section merging preserves live observations
   within the same state revision and discards cached sections across revisions.

Five backend regressions and three real React hook lifecycle regressions were
added. The DOM-only dependency is development-only; no production visualization
dependency or graph engine was added. The pre-fix tests failed on the reproduced
cases. Follow-up verification passed:

- Memory: 149 tests run, two expected skips (147 passing), including all five
  added backend regressions and the existing numeric/provenance safeguards.
- Frontend: 18 Vitest tests passing, including three hook lifecycle regressions;
  TypeScript and official hosted frontend rebuild passed.
- Chat: 15 learning-review tests and the real Memory save/evidence test passed.
- SDK source validation passed; Memory's audited CLI/MCP execution hashes and
  the focused Core navigation/effect admission test were refreshed and passed.
- Unused imports and scoped diff checks passed. The fixes add no visual/layout
  changes; a fresh hosted browser session was not part of this follow-up. DOM
  lifecycle tests exercise actual React effects, request cancellation and merges.

## Independent review fixes after `5e3aa1de`

The independent review reproduced two remaining defects on isolated data:

- Two valid source-only facts became one exhausted result when a long source
  occupied the global passage sample. Verification now reads ranked pages per
  node in one batched query, advances undecided nodes past damaged prefixes, and
  retains at most three verified passages from each sample. Finding one valid
  sample stops further scanning for that node. Indexed continuation and response
  byte limits remain separate and unchanged.
- Attaching app references changed the Sources section while leaving the fact
  revision and `state_revision` unchanged, both before compilation and with a
  wiki already stale. The existing batched source-state projection now includes
  reference count/latest update, and read revisions include `external_refs` so
  earlier detail cursors are explicitly rejected after attachment. References
  without ingested content retain `source_state=unknown`.

Four backend regressions cover the long/short source pair, a nine-passage damaged
prefix followed by valid evidence, bounded reads when a valid sample precedes a
damaged remainder, and reference attachment before compilation/while stale with
cursor rejection. Long/short-source, damaged-prefix and reference-state cases
failed before the fix. A fourth real React hook test verifies the refreshed
Sources section when only the reference state changes. Original passage SHA
validation is preserved. No
production frontend code, assets or dependencies changed; no browser/layout
session or new frontend build was needed for this backend and test-only fix.

Final verification passed:

- Memory: 153 tests run, two expected skips (151 passing), including the nine
  review regressions and the existing paging, integrity and graph query checks.
- Frontend: 19 Vitest tests and TypeScript checking passed.
- Chat: 15 tests across the learning regressions and real Memory save/evidence
  suites passed.
- Mounted Core CLI/MCP Memory integration and the focused Core Memory effect/
  execution-authority test passed. Only Memory's execution hashes were refreshed.
- SDK validation used the explicit built-in source root and returned `valid=true`.
  Scoped unused-import checks and source diff checks passed.

The synthetic fixture was repeated. Cards have the same 976 bytes and five-card
batch has the same 5,503 bytes as the preceding review. Map query counts remain
10 (unsearched) / 13 (searched), with the same 112,919-byte payload for 100 nodes.
Including reference changes in cursor binding adds one SELECT per paged retrieval:
context is 29 SELECT/WITH statements, one card and five cards are both 14, history
headers 15, exploration 16, and explicit full inspection 26. The per-card reference
state adds no SQL statement to the shared card projection and no response field.
These are temporary-data measurements, not production latency claims.

## Synthetic retrieval measurements

Reproduce with `python3 apps/memory/tests/retrieval_benchmark.py`. The script creates
a temporary database with 100 nodes, bodies around 13,800 characters and fifteen
updates of one node (retained revision snapshots). It then adds a dependency,
parallel related edge and contradiction for exploration. It never opens workspace
Memory data. JSON bytes use Python's UTF-8 `ensure_ascii=False` serialization;
SELECT counts include read revision/state projection queries and recursive WITH.

Observed follow-up review run (elapsed time varies with host load):

| Operation | SELECT/WITH statements | JSON bytes | Local elapsed |
| --- | ---: | ---: | ---: |
| Map, 100 nodes | 10 | 112,919 | 7.68 ms |
| Searched map, same 100 nodes | 13 | 112,919 | 23.69 ms |
| Context, textual limit 8 | 28 | 8,840 | 24.03 ms |
| One card | 13 | 976 | 3.77 ms |
| Explicit full inspection | 25 | 450,261 | 8.52 ms |
| Ten history headers | 14 | 2,572 | 3.39 ms |
| Five cards, one call | 13 | 5,503 | 3.56 ms |
| Three graph edges / three cards | 15 | 3,520 | 4.58 ms |

The map avoids detailed hydration: searched and unsearched projections have the
same payload and query counts stay bounded as node count grows. The supplied
report's 516-SELECT searched-map result is a useful prior observation, not a
controlled before/after latency experiment with this fixture. State-rich cards
are larger than the former bare map summary; the UI defaults to thirty cards and
caps its visible subgraph at forty.
The review's state fingerprint adds 46 serialized bytes per card and no SQL
statements in this fixture. The compact context's byte size remains unchanged.

The context returns seven items within its byte budget and correctly reports
`retrieval_has_more=true`, a search cursor and a non-exact/null total. Tests also
exhaust all 100 results through continuation with a larger budget and separately
recover IDs omitted for bytes. The full audit remains intentionally available;
ordinary card lookup reduces this fixture's payload by over 99%.

Elapsed values are individual local runs under shared-machine load, not production
latency, a statistical distribution, or an SLA. Calls/bytes are measured directly;
provider token counts and production latency remain to be evaluated.

## Automated verification

- Full Memory fast-level suite: 144 tests, two integration/full-wrapper tests
  skipped by that level. Twelve new navigation regressions cover cycles, parallel
  edges, directional hops, progressive byte pages, stale cursors, critical edges,
  query counts, long content/history, alias/scope/time, removed sources, Storage
  links, bounded chat provenance, read-only behavior, output schemas and a
  subprocess background hook without UI.
- Fourteen focused context/navigation tests also passed after the final candidate
  count correction: exact search totals exclude graph-expanded neighbors, while
  `retrieved_candidate_count` includes them.
- Mounted Core CLI/MCP Memory integration executed separately and passed.
- Fifteen Chat Learning/evidence regression tests passed. They verify approved
  fact replacement, revision guards, immediate compilation, UUID/source locator
  evidence and retained conversation provenance. The persisted fact assertion now
  explicitly requests the selective content section.
- Frontend: TypeScript production build and fifteen Vitest tests passed, including
  bounded subgraph merging, parallel edge preservation, native inspector sections
  and confidence/verification distinctions.
- Official `maverick app memory frontend build` succeeded and generated hosted
  asset metadata. SDK validation returned `valid=true`; scoped unused-import
  checking and `git diff --check` passed.
- Memory's CLI/MCP audited descriptor and execution hashes were refreshed. A
  focused Core test validates the declared navigation tools, all Memory effect
  classifications and both audited execution closures.
- Live official MCP calls for `memory_explore` and `memory_get_nodes` returned
  compact cards and successful read-only responses on existing workspace nodes.

Two broader Core inventory tests also ran. That run failed independently of Memory:
the repository-wide inventory already differs for other apps (including Agents),
and Browser's CLI admission reports an unclassified effect. Their static global
counts are also stale relative to the current app catalog. This change updates
the expected MCP count only by Memory's two added tools; it does not re-audit or
reclassify unrelated applications. The focused Memory admission test passes.

## Browser and renderer verification

Read-only Browser Lab sessions inspected the hosted Memory UI at 1440×900 and
390×844. They opened the keyboard list, selected existing memories, inspected
Content/Sources/History, and displayed directed incoming connections with reasons.
Screenshots confirmed native controls, selected-node placement, scrollable mobile
panels and preserved app vector icons. No production Memory records were created
or changed. Memory-related console errors were absent during the final interaction
window; an earlier mobile session recorded frame-auth renewal errors before a
successful reload, plus normal Browser Lab service-worker/sandbox warnings.
A later snapshot confirmed that shell context parameters reopen four referenced
nodes and insert a fifth node opened by deep link, with the context banner intact.
Supplementary browser actions then became unavailable because platform tools
returned `authentication_required`; no authentication state was changed by this work.
After the platform restart, a new session verified following a connection and
returning to the previous node. The context/deep-link check exposed a render race:
navigation could read stale graph references and overwrite the loaded context.
Graph references now update synchronously before publishing React state. Three
fresh hosted navigations preserved all four referenced nodes plus the inserted
fifth node, and restored the seventeen-node workspace view on every attempt.

Cytoscape 3.34.3 contributes one dynamically imported chunk of 443.04 kB raw /
141.98 kB gzip. Main app code is about 40 kB raw / 13 kB gzip, besides the shared
React/API bundle. The old app-owned physics/drawing/gesture engine was removed;
there is no second renderer or continuous simulation. Labels participate in the
initial CoSE layout and selected nodes have a minimum readable zoom. Mobile's
overview remains spatial; the keyboard list and focused panel provide full titles.

Renderer choices follow the [official Cytoscape documentation](https://js.cytoscape.org/).
App-local Git attributes preserve whitespace in the generated library's GLSL
template literals, allowing source whitespace checks without rewriting vendor code.
This validates the small integration and its real build cost; larger graph/device
profiling and a controlled usability comparison with the former canvas remain
future evaluation work.

## Operational limits

The one-to-three-call retrieval path is supported by context → explore → selective
evidence, and five cards need one call. This is a design target, not proof that
every real question completes within three calls. Semantic search and model-based
entailment were not added; unknown paraphrases remain unverified.

Queue progress assumes the app is enabled and the platform lifecycle worker is
running. The subprocess regression verifies app behavior without an open UI;
it does not simulate every platform outage. Two seconds is a soft between-job
budget, not a hard per-job deadline. Storage reindexing remains explicit.

Indexed card state is cheaper than live source verification. Read selective
evidence before treating a source as freshly observed. Temporal retrieval filters
validity metadata; historical overwritten content requires explicit revisions.
Conversation context views reopen reference IDs against current state; they are
not immutable historical UI snapshots. Cursor invalidation is explicit, requiring
the caller to restart and deduplicate stable IDs after concurrent changes.
