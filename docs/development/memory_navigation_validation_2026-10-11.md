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

## Synthetic retrieval measurements

Reproduce with `python3 apps/memory/tests/retrieval_benchmark.py`. The script creates
a temporary database with 100 nodes, bodies around 13,800 characters and fifteen
updates of one node (retained revision snapshots). It then adds a dependency,
parallel related edge and contradiction for exploration. It never opens workspace
Memory data. JSON bytes use Python's UTF-8 `ensure_ascii=False` serialization;
SELECT counts include read revision/state projection queries and recursive WITH.

Observed final run:

| Operation | SELECT/WITH statements | JSON bytes | Local elapsed |
| --- | ---: | ---: | ---: |
| Map, 100 nodes | 10 | 108,319 | 14.92 ms |
| Searched map, same 100 nodes | 13 | 108,319 | 46.64 ms |
| Context, textual limit 8 | 28 | 8,840 | 50.39 ms |
| One card | 13 | 930 | 5.93 ms |
| Explicit full inspection | 25 | 450,261 | 15.14 ms |
| Ten history headers | 14 | 2,526 | 8.26 ms |
| Five cards, one call | 13 | 5,273 | 5.43 ms |
| Three graph edges / three cards | 15 | 3,382 | 7.50 ms |

The map avoids detailed hydration: searched and unsearched projections have the
same payload and query counts stay bounded as node count grows. The supplied
report's 516-SELECT searched-map result is a useful prior observation, not a
controlled before/after latency experiment with this fixture. State-rich cards
are larger than the former bare map summary; the UI defaults to thirty cards and
caps its visible subgraph at forty.

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
