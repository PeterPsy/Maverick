# Memory reliability audit fixes

Scope: built-in Memory, its source/CLI/MCP contracts, inspector/sidebar, and Chat
Learning's approved-fact save path. Tests use isolated temporary Memory data.

## Implemented behavior

| Audit finding | Change and regression evidence |
| --- | --- |
| Opposing citations accepted | Conservative ordered compatibility gates support. Regressions cover negation, changed values/dates/units, swapped participants, uncertainty, signed numbers including Unicode minus, comparison operators and interrogatives. Decimal cases include `.5` versus `-.5`, `5` and `.05`, signed leading decimals and leading-comma decimals through ingestion/compilation. Whole numeric expressions are validated before tokenization; unsupported numeric formats stay unverified, even when identical. Recognized contradictions and unverified relevant passages retain original text separately. This is not general semantic entailment. |
| Old facts marked fresh | Generated nodes track current source content; explicit attachment/update/replacement operations and guarded revisions preserve curated notes and expose conflicts. Stale compiled facts are omitted from compact context. Current `body_text` is preserved before and after recompilation; historical or contradictory source excerpts may still appear in dedicated evidence fields. |
| Graph search crash and hidden source hits | Normalized timestamps feed graph projection; sidebar trusts backend matches. A source-only query traverses search, graph and backend response. |
| Evidence lost to partial notes; zero edges expanded | Candidates from nodes, pages, claims and current chunks are ranked before the final limit. Project/person scope applies in SQL before every channel limit and related expansion. A regression with 110 out-of-scope matches retains the scoped result in all four channels. Complete matches precede partial matches; direct results precede related nodes. Weight/confidence thresholds preserve zero. |
| Archive scanned on every read | Schema/version/shape checks replace whole-index integrity scans. Explicit maintenance verifies/repairs the index; selected chunks are still hash checked. |
| Oversized reads and repeated compilation I/O | Compact SQL and batched evidence avoid full pages/claims; chunks load once per compile; unchanged input hashes reuse completed runs. Source versions/chunks have bounded pagination. |
| A → B → A; identical imports; leases; read writes | Explicit current pointer is independent of immutable deduplication. Identical inline and remote Storage imports keep an already fresh page current and add no ready job. Unchanged remote observations preserve reference revisions and consecutive compilations reuse the same completed run. Exhausted leases fail terminally. Read-only freshness is persisted by explicit operations. |
| Confidence, duplicates, removal | New unspecified confidence defaults to 0.5; zero survives claims and context. Scoped content identity deduplicates repeated remember. Exclusion, source removal and merge preserve audit data and suppress ordinary retrieval. Full search, direct and related context, wiki results and Storage projections share the active-source reference boundary. Removed references, cached preview text and preview/export requests are absent from ordinary results before and after maintenance, while inspection retains the external reference and versions. Ordinary compile neither fetches nor restores removed sources. Explicit remote reimport restores the source and queues reconciliation. Deleted generated nodes can be reimported. |
| Missing inspector controls | Supporting/conflicting passages, checked chunk expansion, source history, revisions, complete relationships, correction, scope/validity, duplicate merge, exclusion, source removal and node deletion are available. Excluded nodes remain deletable with revision checks; correction, verification and merge controls require restoration first. |
| Chat saves evidence but retains old fact | Approved text is separate from evidence, replacement is explicit, reviewed match guards are forwarded, and callback verifies the persisted fact and revision before accepting success. Type/confirmation/project/conversation provenance reaches context. |

Schema v6 retains the v4 foundation and invalidates previously supporting v4/v5
citations pending the stricter numeric support check. Original passages remain stored;
affected pages become stale and receive deduplicated recompilation jobs. The
compiler's semantic revision also prevents reuse of old support decisions. The
migration does not rewrite existing confidence values or curated facts.

## Validation

Second reviewer follow-up checks: Memory backend full profile **119 tests passed**;
`core.app-sdk.validate` returned `valid: true` with no issues. Unused-import
checking and the scoped Git whitespace check passed. This follow-up changes only
backend logic, schema metadata, tests and documentation; frontend build, browser
and Chat checks were not rerun.

The previous follow-up passed **115 backend tests**, **18 frontend tests**,
TypeScript and the official `maverick app memory frontend build --json`.

Backend regressions are in `apps/memory/tests/test_audit_regressions.py`,
`test_review_regressions.py` and `test_decimal_and_reference_regressions.py`, with
existing contract/integration coverage retained. The second follow-up covers the
two newly reported sequences, unsupported numeric forms, positive decimal cases,
v5→v6 verification revocation/recompilation/cache behavior and retained audit data.
Earlier coverage includes all six first-review sequences, the v4 migration and
meaningful remote reference changes that require recompilation.
Frontend coverage includes disabled active-only actions and enabled
restore/delete actions for excluded nodes, alongside conflicts and zero confidence.
All reproduction data is temporary; workspace memories are untouched.

Earlier audit validation ran Chat's fast profile (**113 tests, 2 expected skips**),
including an actual temporary Memory replacement and rejection of a receipt
retaining the old body, and captured the installed desktop/mobile inspector.
These Chat/browser checks were not rerun for this Memory-only follow-up; excluded
UI state is checked through rendered markup rather than workspace mutations.

Local synthetic no-result context measurement, five runs per archive size:

| Source chunks | Median request time | Content files read |
| ---: | ---: | ---: |
| 0 | 4.61 ms | 0 |
| 98 | 4.15 ms | 0 |
| 980 | 4.05 ms | 0 |

These are the earlier audit's function-level local measurements, not production
latency promises. Returned-result queries and remote compilation latency have not
been benchmarked by this follow-up.
The regression also forbids archive reads on a missing query. Returned evidence
continues to use SHA verification.

## Practical limits

The deterministic citation gate deliberately leaves unknown paraphrases
unverified. It is not a general entailment model. Semantic retrieval and selective
model verification remain optional future additions requiring evaluation against
real queries; this change introduces neither embeddings nor inference costs.

Foreground maintenance runs while Memory is visible, at most three compile/lint
jobs, stopping between jobs after two seconds. One job can exceed that soft
budget. Immediate agent workflows still explicitly drain bounded ready work.
External Storage reindexing remains a governed Storage operation.

Merge preserves the chosen target fact instead of inventing a combined assertion.
Node/source removal retains audit content; original documents remain owned by
Storage or their originating app. History and excluded evidence require explicit
retrieval options.
