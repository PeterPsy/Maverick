# Agentic multimodel runtime epic

Status date: 2026-08-28

Target: Phase 4B Full Workspace tool surface implemented; Phase 4C-D
context and provider-compatibility closure remains open;
remote agentic release remains **NO-GO**.

Normative source: Maverick Agentic Multimodel Runtime specification, revision
2.1 (2026-08-16), the definitive parity plan in workspace Storage, and ADR
0010.

Checked implementation items mean that the repository gate and its focused
tests passed for the recorded source. They do not mean that a provider live
probe ran, that a behavioral certificate was issued, or that preview, canary,
or production activation is approved.

## Phase 0 — material containment closure

- [x] Hosted, Google, and OpenRouter agentic switches default off; unknown
  hosted-agentic identities fail closed while exact Codex and
  `plain_hosted_chat` retain their prior paths.
- [x] Remote creation and dispatch are contained before persistence/egress;
  browser declarations, legacy `declared_remote_data_class`, policy ids, and
  `workspace_internal_fake` grant no authority.
- [x] The revision-CAS containment saga disables bindings, suspends profiles,
  revokes legacy remote certificates, and quarantines ambiguous sessions after
  complete paginated inventory.
- [x] Chat and Settings show authoritative containment/governance projections
  without browser classification controls or credential authority.
- [x] The reviewed real-store containment operation and post-apply verification
  were materially completed before this phase. Recorded evidence:
  - source containment revision
    `69d9e10fea641f805c1c52801b7fd60a027b02f9`;
  - applied plan digest
    `02484a30f9ea7254c5deebd69e5af4416a22d8aecc006d81b7b5d6aad9c4578d`;
  - audit saga `4a6ab3ee-8b55-40c4-9dd6-2eba17bd9bdc`;
  - apply artifact SHA-256
    `5cd77cf01ab3e4ed12ca0ab76d3774dadf0482bd892821fb8883ef3cb2ab6898`;
  - post-apply zero-target digest
    `56253919e93461e67b62a068e6e8718638475d05173dfff97b2912dcbeed2e77`;
  - post-apply artifact SHA-256
    `c6daa0b542edc92ef09116b323b1b024d3d1f94ef53aa85344eb55ea4aad733c`.

This is a material P0 containment record only. It is not a remote release,
provider certification, preview/canary, migration approval, or production
completion claim.

## Phase 1 — security boundary and certified TCB

### Attestation, classification, and egress

- [x] Workspace fake-data attestation is an explicit actor-attributed,
  timestamped, scoped, revocable CAS record in the official JSON/document-store
  boundary, with redaction-safe audit and operator-only issue/revoke commands.
- [x] API, Chat, and Settings receive only a read-only projection. Attestation,
  resource classification, and the final egress decision remain distinct;
  client inputs, labels, flags, and policy ids cannot manufacture any of them.
- [x] A fake-data declaration can only narrow policy. It never promotes real,
  secret, workspace-internal, or unclassified content to public/fake, and the
  legacy declaration is non-authoritative and absent from continuations.
- [x] `workspace_internal_fake` requires the exact resource-derived
  classification, an active workspace-matching attestation whose scope covers
  the resource, and an egress policy that allows the class/destination. Current
  contained profiles remain public-only, disabled, non-selectable, and NO-GO.

### Resource-derived provenance and private state

- [x] Canonical provenance/trust/data-class records use a restrictive,
  fail-closed join. Prompt, orchestration, skill, attachment, app reference,
  filesystem/tool result, and provider-private sources remain distinct.
- [x] Filesystem/tool results bind classification to the exact observed resource
  identity, revision, and digest. Missing/incoherent classification becomes
  `unclassified` and cannot egress.
- [x] Encrypted provider-private state persists only redaction-safe source
  digests/classes/trust, effective class, codec, request id, and turn generation;
  content, credentials, and resolution authority never enter public APIs/audit.

### Certified schemas and execution TCB

- [x] Tool schemas are public only when Core-owned, explicitly public, and
  covered by the exact certified TCB. App-owned, CLI/MCP-dynamic, omitted, or
  uncertified schemas fail before egress with an allowlisted structured reason.
- [x] One code-owned deterministic certified-execution manifest covers data
  governance/classification/egress, API and app admission, input/request
  composition, catalog/schema, ledger/store/private state, lifecycle/recovery
  boundary, capability projection, Chat/Settings governance, and provider
  codec/transport/live policy.
- [x] Manifest v7 records six maintained transitive dependency contracts. The
  audit walks package initializers and the admission, input, egress, tool,
  state/lifecycle, and served-governance closures; it includes the exact
  `core/inter_agent/generalist_context.py` closure and both operator live-probe
  entrypoints, and rejects any newly reached local dependency that is not
  already hashed by the TCB.
- [x] Suite, bundle, signing, verification, issuance/publication, execution
  binding, and live status derive from that manifest and digest. The publisher
  recomputes it; runtime drift or legacy missing TCB identity fails before
  create, continuation, refresh, or dispatch. Exact Codex is not reclassified
  as hosted remote.
- [x] Google and OpenRouter suite v17 / matrix
  `2026-08-28-r17-p4b-full-workspace-tcb7`
  manifests retain ordered `fixture_contract` then operator-only `live_probe`;
  ordinary checks explicitly select only the fixture step.

### Filesystem confinement

- [x] Read/list/write and shell cwd use a pinned workspace root and
  descriptor-relative component opens with `O_NOFOLLOW`/`O_DIRECTORY` where
  available. Verified resources are never reopened by pathname, `.git` is not
  traversed, and root/parent/final symlink and rename swaps fail closed.
- [x] Chunk reads and listing cursors bind resource identity/version, detect
  mutation, preserve UTF-8 boundaries, and feed resource-derived
  classification. Repeated Linux race tests leave zero escaped reads/writes.

### Effective capabilities and UI governance

- [x] One effective snapshot intersects certificate, profile ceiling, workspace
  binding, actor policy, live authority, feature flags, and provider health.
  It exposes filesystem read/write, shell, CLI, MCP, skills, attachments, app
  references, confirmations, recovery, provider/data policy, certificate/suite/
  expiry, and TCB posture without credentials.
- [x] The same snapshot gates session/turn admission, continuation/refresh,
  request building, tool catalog, APIs, Chat, and Settings. Skills, unsupported
  attachment modes/app references, CLI/MCP/shell, and unauthorized writes are
  rejected before persistence or provider work with public allowlisted reasons;
  unsupported input is never silently ignored.
- [x] Exact Codex and `plain_hosted_chat` non-regression tests preserve their
  established behavior while hosted-agentic paths without effective authority
  fail closed.

### P1 exit gate

- [x] False data classification: `0`.
- [x] Undetected TCB drift: `0` (including transitive generalist-context drift
  across signing, verification/publication, binding, and live status).
- [x] Filesystem escape in repeated Linux race tests: `0`.
- [x] Capability overstatement: `0`.
- [x] Unsupported context silently ignored: `0`.

## Phase 2 — provider-step journal, ledger, pairing, and recovery

### Durable request saga and preliminary proposals

- [x] `provider_step_journal.json` and the document-store collection implement
  the same revision-CAS state machine for request ready/journaled, acceptance,
  stream/staged state, proposal/disposition/result identities, pairing,
  immutable request-input lineage, private final-output outbox identity,
  delivery acknowledgement, commit, rollback, and quarantine. The saga is
  explicitly ordered across collections; it does not claim a cross-collection
  transaction.
- [x] Every decoded provider call is inserted into the preliminary tool ledger
  before catalog resolution, schema validation, policy, or budget disposition.
  The record retains the safe provider name, call id/index/ordinal, request id,
  private argument locator and HMAC, policy revision, and authority digest;
  the resolved handle remains nullable and complete arguments remain encrypted.
- [x] Exact call replay deduplicates. A reused call id with different name or
  arguments fails closed. Unknown, revoked, not-authorized, schema, budget,
  parallel, and malformed dispositions remain persisted and pairable.

### Stream accounting, effects, and provider state

- [x] Google and OpenRouter retain every indexed call, including OpenRouter
  indices above zero and calls decoded before a later terminal stream error.
  Because parallel execution remains unsupported, all calls are journaled;
  calls inside the remaining tool budget receive `parallel_denied` and overflow
  receives `budget_denied`. None is silently discarded or executed.
- [x] Provider response state is encrypted as staged state and never read as
  authoritative continuation state. Promotion occurs only after a validated
  final output or complete proposal → disposition → result/denial → pairing
  chain, followed by provider-state CAS and journal commit.
- [x] A final response is encrypted behind a deterministic Core-private outbox
  locator and attached to the journal before stream completion or commit.
  `runtime.output.final` and `provider.execution.completed` use stable delivery
  identities and independent durable acknowledgements; recovery drains the
  same bytes without a second provider request.
- [x] Runtime tool events enforce persisted proposal → proposed event →
  validation/disposition → started event → effect boundary → persisted result
  → completed/failed event. An ambiguous mutating boundary becomes
  `execution_unknown` and is not replayed.

### Productive recovery and quarantine

- [x] The exact pinned binding, adapter, provider protocol/API, and codec are
  checked during recovery; no old codec is silently migrated. Google and
  OpenRouter inspectors reconstruct only call-id/name pairing facts from the
  encrypted staged bytes.
- [x] Recovery runs from backend startup/worker-loss, continuation
  pre-admission, hosted pre-prepare, execution failure, uncertain cancellation,
  and explicit adapter recovery. It completes only provable WAL halves,
  terminal results, pairing consumption, provider-state promotion, and commit;
  explicit no-state provider terminals can return to the prior commit.
- [x] A committed ready pairing belongs only to its original active turn. Its
  journal id, turn id, provider request id, private-state generation, and exact
  non-tool input digest must all match before continuation. Ordinary new turns
  are rejected before persistence/provider transport and never inherit or
  silently consume an older pairing.
- [x] Step/tool/token/cost/time termination, cancellation, authority or
  certificate revocation, egress denial, and execution failure cannot leave a
  ready provider pairing on a running session: same-turn recovery seals it or
  the journal/session enters `recovery_required`.
- [x] Unprovable acceptance, state, pairing, or tool execution transitions the
  session by bounded reread/retry status CAS to `recovery_required` before any
  diagnostic write. Journal containment is retried independently; bounded
  Core-private detail is best-effort, and private-payload, audit, projection, or
  journal-CAS failure cannot unblock the session. Only an allowlisted public
  reason is persisted. Queue, continuation, prepare/dispatch, and runtime token
  validation read the persisted journal and reject unresolved state.
- [x] API, Chat, and Settings continue to show only `recovery_required` and its
  safe public cause; provider bytes, argument/result bodies, private locators,
  and recovery detail are absent.

### P2 exit gate

- [x] Proposal records minus provider calls observed: `0`.
- [x] Nonterminal observed calls outside `recovery_required`: `0`.
- [x] Next-turn pairing failures in Google/OpenRouter crash matrices: `0`.
- [x] Duplicate side effects across repeated recovery: `0`.
- [x] `proposed` or `started` events emitted after the effect boundary: `0`.
- [x] Staged provider states used as authoritative before commit: `0`.
- [x] Productive lifecycle recovery entry points missing: `0`.
- [x] Terminal provider pairings left on running sessions: `0`.
- [x] Cross-turn inputs silently absorbed by older pairings: `0`.
- [x] Quarantines blocked by diagnostic or first-CAS failure: `0`.
- [x] Provider retries or duplicate final events after durable final commit: `0`.

## Phase 3 — budget reservation and governed finalization

### Separate durable budgets and protected resources

- [x] Provider requests and provider tool proposals consume distinct counters.
  Every exploration proposal consumes at most one durable tool-budget charge;
  parallel overflow is journaled and denied without creating another provider
  step. An accepted charge shares the proposal's journal CAS. Restart
  reconstructs provider steps, tool charges, paired-result bytes, reported
  input/output/cost, and conservative missing-usage reservations from
  provider-step journal schema v3.
- [x] Each hosted adapter pins a finalization policy. Google reserves two
  2,048-token / 550,000-micro-USD / 20-second attempts; OpenRouter reserves two
  2,048-token / 35,000-micro-USD / 20-second attempts. Each cost allocation
  covers the real conservative estimator for a complete terminal request at
  the hosted input ceiling, including retained context/provider state and a
  maximum admitted tool result.
  The second attempt is the
  sole permitted recovery. The live profile ceiling must retain the current
  final attempt plus any future recovery before dispatch.
- [x] The controller exposes remaining provider steps, tool calls, output
  tokens, micro-USD cost, wall time, and `finalization_reserved`. Request max
  output, estimated input/cost, phase, tool charges, usage, and a separate
  immutable request-control digest are durable. Missing finite cost authority,
  a terminal request above its per-attempt certified cost ceiling, deadline
  exhaustion, or live-policy narrowing fails visibly instead of consuming the
  reserve.

### Toolless closure and terminal behavior

- [x] Coarse eligibility and credential availability are checked before catalog
  materialization. Request projection stages (but does not persist or audit)
  egress decisions until the provider-specific cost preflight passes. An
  exploration candidate that crosses the reserve is discarded and replaced by
  a tool-less `finalization` candidate before any egress commit, request journal,
  or provider transport. When tool calls are exhausted—or another protected
  resource reaches its reserve—the next request likewise has an empty Core
  catalog and a final trusted system instruction placed last.
- [x] Hosted synchronous tool dispatch has a pre-terminal deadline and
  cancellation control. A slow read is CAS-fenced with a deterministic ledger
  error before any private result write. `executing` persists a unique lease id
  and UTC expiry; success requires revision, lease, and an unexpired deadline in
  one collection CAS (Mongo server time or the locked local atomic-replace
  path). A worker paused after its last cooperative check cannot become
  authoritative after expiry even when the timeout CAS is delayed.
  Finalization proceeds with the paired error. Ambiguous non-read effects remain
  `execution_unknown` and quarantine fail closed.
- [x] OpenRouter's finalization instruction is appended only to the current wire
  payload. It is absent from the encrypted durable history, so a later
  exploration turn receives tools and no stale closed-catalog instruction.
- [x] OpenRouter serializes `tools: []` and `tool_choice: none`; Google omits
  `tools`. Both codecs require the exact Core finalization instruction and
  reject phase/catalog mismatches before transport. The operator live probes
  now use the same tool-less final request, but no live probe was run here.
- [x] Empty or whitespace-only `text_final` is never committed or emitted as a
  healthy final output. It is durably marked invalid, the staged provider state
  is rolled back to the last commit, and `agent_final_output_empty` is visible.
- [x] A tool proposed during finalization is first written to the preliminary
  ledger, then receives a persisted `budget_denied` result and one paired
  `finalization_recovery` request with the catalog still empty. A second tool
  proposal is denied, no fourth request is sent, and the remaining pairing is
  quarantined as `recovery_required` with a structured terminal failure.
- [x] Every failure path emits `runtime.error` plus non-zero provider
  completion; a successful path requires a non-whitespace final output. No
  terminal path silently drops a proposal or leaves an ordinary running
  session with an unconsumed provider pairing.

### P3 exit gate

- [x] Empty/whitespace healthy final outputs: `0`.
- [x] Requests carrying tools after tool-budget exhaustion: `0`.
- [x] Silent terminal turns: `0`.
- [x] Finalization step/output/cost/time reserve violations: `0` in the
  deterministic P3 matrix.
- [x] Finalization recovery attempts beyond one: `0`.
- [x] Codex profile/artifact revision changed by P3: `0`.

## Phase 4A — semantic envelope and materialization

- [x] Core compiles every hosted request from semantic-envelope schema v1 and
  keeps platform, runtime/capability, workspace, agent, user, governed context,
  attachment, app reference, skill, tool schema/result, finalization, and
  provider-state blocks distinct.
- [x] Complete bounded `AGENTS.md` chains are resolved root-to-workdir for every
  provider step. Complete invoked `SKILL.md` files use the same descriptor-
  confined, identity/revision-fenced chunk reads; symlink, escape, mutation,
  invalid UTF-8, oversize, and missing-source cases fail closed.
- [x] Canonical source-snapshot and destination-projection digests are separate.
  The latter binds compiler id/revision, provider protocol, phase, roles,
  transformations, tool/result identities, egress decisions, and exported
  content digests.
- [x] Provider-step journal schema v4 persists both digests and compiler
  identity. The semantic compiler runs on continuation/finalization/recovery
  steps, so instructions and skills are re-injected rather than trusted to
  provider history after resume or future compaction.
- [x] Unknown mandatory provenance and incomplete projection fail before
  provider dispatch. Deterministic tests cover stable/changed digests, nested
  instruction scope, full skill content, separated inputs, and journal evidence.
- [x] Hosted adapter 12, Google profile revision 20, OpenRouter profile revision
  19, suite 16, matrix `2026-08-28-r16-p4a-semantic-envelope-tcb6`, and TCB
  manifest v6 are immutable contained candidates. No live probe, certificate,
  remote activation, or Codex profile/artifact change is part of P4A.

## Phase 4B — Full Workspace tool surface

- [x] `full_workspace_contract_revision=codex-baseline-v1` is a code-owned,
  atomic profile/certificate/binding/live-authority contract. Any missing
  required capability or handle rejects the claim or live refresh instead of
  producing a partial agent.
- [x] Descriptor-confined search and chunked reads are stable and versioned;
  create/no-replace and atomic exchange, exact edit/ordered patch with bounded
  diffs, rename, and quarantined recursive delete are version-fenced and
  reject symlink/final-entry/parent races.
- [x] Every mutation can bind a root-to-target `AGENTS.md` scope digest and
  rechecks it before effect. Platform `runtime/` and `.git` are excluded from
  agent filesystem enumeration and access.
- [x] Hosted shell runs at fixed `/workspace`, masks platform runtime state,
  exposes no host workspace path, uses an ephemeral HOME/TMP, read-only system
  tooling, a disconnected network namespace, bounded output, and group timeout
  cleanup.
- [x] Session-owned long processes support bounded streaming status, stdin,
  interrupt, timeout, redacted durable records, session cleanup, and the common
  orphan reaper.
- [x] Core/app CLI and MCP use discovery-first certified wrappers over the
  official registries. Invocation tokens bind session, target, and registry;
  the real runner rechecks policy. Authorized collaboration/inter-agent
  commands are reached through the same official surfaces, not a shadow
  implementation.
- [x] Hosted results use the shared Codex result compactor before provider
  egress. Confirmation remains in the common durable ledger, and the full
  contract also requires skill, attachment, app-reference, interrupt, and
  recovery capabilities.
- [x] Adapter 13, Google profile revision 21, OpenRouter profile revision 20,
  suite 17, matrix `2026-08-28-r17-p4b-full-workspace-tcb7`, and TCB manifest
  v7 are immutable contained candidates. The profiles intentionally remain
  read-only and do not claim the full-workspace contract; Phase 4D must create
  new full revisions after compatibility closure. No live probe, certificate,
  remote activation, or Codex profile/artifact change is part of P4B.

## Later parity and release gates — still open

- [ ] Phase 4C-D complete context/interaction management and exact provider
  compatibility closure, then create new certified full-workspace revisions.
- [ ] Run each complete provider manifest on an exact clean deployable commit:
  deterministic fixture, operator-only synthetic live probe, behavioral
  validation, signing, verification, and immutable certificate publication.
- [ ] Complete provider onboarding, leakage/security review, one-workspace
  canary, rollback rehearsal, and explicit preview release decision.
- [ ] Close all production blockers in `SECURITY.md` and
  `docs/security/production_readiness.md` under a separate security review.

`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` remains false. No remote binding,
profile, or certificate is enabled by P4B; no Google/OpenRouter session, provider
HTTP/SSE request, live probe, real-store containment/migration apply, canary,
production release, or push is part of this closure. A backend restart after
the verified commit is an operational code/schema reload only and does not
alter those control-plane states. Exact Codex stays on profile revision 12 and
its existing artifact digest.

## Evidence and acceptance links

- Architecture decision: `docs/adr/0010-agentic-multimodel-runtime.md`
- Runtime/provider contract: `docs/reference/runtime_provider_model.md`
- Certification procedure: `docs/runbooks/agentic_certification_evidence.md`
- Preview activation and rollback: `docs/runbooks/agentic_provider_preview.md`
- Provider matrices: `docs/reference/google_agentic_certification_matrix.md`
  and `docs/reference/openrouter_agentic_certification_matrix.md`
- Security posture: `docs/security/threat_model.md` and
  `docs/security/production_readiness.md`
