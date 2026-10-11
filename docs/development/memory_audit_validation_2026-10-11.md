# Memory reliability audit fixes

Scope: built-in Memory, its source/CLI/MCP contracts, inspector/sidebar, and Chat
Learning's approved-fact save path. Tests use isolated temporary Memory data.

## Implemented behavior

| Audit finding | Change and regression evidence |
| --- | --- |
| Opposing citations accepted | Ordered assertion compatibility gates support; negation, changed values/dates/units, swapped participants and uncertainty cannot become supporting citations. Recognized contradictions and unverified relevant passages retain their original text separately; ambiguous curated facts receive reconciliation findings. |
| Old facts marked fresh | Generated nodes track current source content; explicit attachment/update/replacement operations and guarded revisions preserve curated notes and expose conflicts. Stale compiled facts are omitted from compact context. |
| Graph search crash and hidden source hits | Normalized timestamps feed graph projection; sidebar trusts backend matches. A source-only query traverses search, graph and backend response. |
| Evidence lost to partial notes; zero edges expanded | Candidates from nodes, pages, claims and current chunks are ranked before the final limit. Complete matches precede partial matches; direct results precede related nodes. Weight/confidence thresholds preserve zero. |
| Archive scanned on every read | Schema/version/shape checks replace whole-index integrity scans. Explicit maintenance verifies/repairs the index; selected chunks are still hash checked. |
| Oversized reads and repeated compilation I/O | Compact SQL and batched evidence avoid full pages/claims; chunks load once per compile; unchanged input hashes reuse completed runs. Source versions/chunks have bounded pagination. |
| A → B → A; identical imports; leases; read writes | Explicit current pointer is independent of immutable deduplication. Identical import does not invalidate or enqueue. Exhausted leases fail terminally. Read-only freshness is persisted by explicit operations. |
| Confidence, duplicates, removal | New unspecified confidence defaults to 0.5; zero survives claims and context. Scoped content identity deduplicates repeated remember. Explicit exclusion, source removal and merge preserve audit data and suppress ordinary retrieval. Deleted generated nodes can be reimported. |
| Missing inspector controls | Supporting/conflicting passages, checked chunk expansion, source history, revisions, complete relationships, correction, scope/validity, duplicate merge, exclusion, source removal and node deletion are available. |
| Chat saves evidence but retains old fact | Approved text is separate from evidence, replacement is explicit, reviewed match guards are forwarded, and callback verifies the persisted fact and revision before accepting success. Type/confirmation/project/conversation provenance reaches context. |

Schema v4 migration invalidates legacy unverified citations, recovers current
observation pointers from logical source hashes, and queues deduplicated
recompilation. It does not rewrite existing confidence values or curated facts.

## Validation

Final checks: Memory backend full profile **107 tests passed**; Chat fast profile
**113 tests, 2 expected skips**; frontend **17 tests passed**. The official
`maverick app memory frontend build --json` succeeded, including TypeScript;
`core.app-sdk.validate` returned `valid: true` with no issues. Unused-import
checking and the scoped Git whitespace check passed.

Backend regression coverage is in `apps/memory/tests/test_audit_regressions.py`,
with existing Memory contract/integration coverage retained. Chat tests include an
actual temporary Memory save replacing an existing fact and rejection of a save
receipt retaining the old body. Frontend tests cover native inspector actions,
conflicts and zero confidence; TypeScript and the official frontend build are
required. Browser screenshots check the installed desktop and mobile inspector
without modifying workspace knowledge.

Local synthetic no-result context measurement, five runs per archive size:

| Source chunks | Median request time | Content files read |
| ---: | ---: | ---: |
| 0 | 4.61 ms | 0 |
| 98 | 4.15 ms | 0 |
| 980 | 4.05 ms | 0 |

These are function-level local measurements, not production latency promises.
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
