# Agentic multimodel runtime epic

Status date: 2026-08-27

Target: Phase 2 provider-step journal, preliminary ledger, pairing, and
productive recovery implemented; remote agentic release remains **NO-GO**.

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
- [x] Manifest v3 records six maintained transitive dependency contracts. The
  audit walks package initializers and the admission, input, egress, tool,
  state/lifecycle, and served-governance closures; it includes the exact
  `core/inter_agent/generalist_context.py` closure and rejects any newly reached
  local dependency that is not already hashed by the TCB.
- [x] Suite, bundle, signing, verification, issuance/publication, execution
  binding, and live status derive from that manifest and digest. The publisher
  recomputes it; runtime drift or legacy missing TCB identity fails before
  create, continuation, refresh, or dispatch. Exact Codex is not reclassified
  as hosted remote.
- [x] Google and OpenRouter suite v10 / matrix
  `2026-08-27-r10-p2-tcb3`
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
  commit, rollback, and quarantine. The saga is explicitly ordered across
  collections; it does not claim a cross-collection transaction.
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
  Because parallel execution remains unsupported, all calls are journaled and
  then denied together; none is silently discarded or executed.
- [x] Provider response state is encrypted as staged state and never read as
  authoritative continuation state. Promotion occurs only after a validated
  final output or complete proposal → disposition → result/denial → pairing
  chain, followed by provider-state CAS and journal commit.
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
- [x] Unprovable acceptance, state, pairing, or tool execution transitions the
  session by status CAS to `recovery_required`, stores bounded Core-private
  detail, and exposes only an allowlisted public reason. Queue, continuation,
  prepare/dispatch, and runtime token validation reject the quarantined session.
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

## Later parity and release gates — still open

- [ ] Phase 3 finalization reserve.
- [ ] Phase 4 complete semantic envelope, AGENTS materialization, and new tool
  contracts.
- [ ] Run each complete provider manifest on an exact clean deployable commit:
  deterministic fixture, operator-only synthetic live probe, behavioral
  validation, signing, verification, and immutable certificate publication.
- [ ] Complete provider onboarding, leakage/security review, one-workspace
  canary, rollback rehearsal, and explicit preview release decision.
- [ ] Close all production blockers in `SECURITY.md` and
  `docs/security/production_readiness.md` under a separate security review.

`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` remains false. No remote binding,
profile, or certificate is enabled by P2; no Google/OpenRouter session, provider
HTTP/SSE request, live probe, real-store migration/apply/restart, canary,
production release, or push is part of this closure.

## Evidence and acceptance links

- Architecture decision: `docs/adr/0010-agentic-multimodel-runtime.md`
- Runtime/provider contract: `docs/reference/runtime_provider_model.md`
- Certification procedure: `docs/runbooks/agentic_certification_evidence.md`
- Preview activation and rollback: `docs/runbooks/agentic_provider_preview.md`
- Provider matrices: `docs/reference/google_agentic_certification_matrix.md`
  and `docs/reference/openrouter_agentic_certification_matrix.md`
- Security posture: `docs/security/threat_model.md` and
  `docs/security/production_readiness.md`
