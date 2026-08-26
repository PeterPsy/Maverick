# ADR-0010: Agentic Multimodel Runtime Boundaries

## Status

Accepted on 2026-08-16 as the ADR-0 gate for the agentic multimodel runtime.

Phase-0 containment amendment accepted on 2026-08-25 and hardened on
2026-08-26: remote agentic execution
is **NO-GO** until the revision-bound server attestation designed in Phase 1
exists. This amendment supersedes earlier preview-enablement language below;
Codex agentic and plain hosted text are not contained.

This decision authorizes implementation in the order described below. It does
not authorize production use or remote-provider processing of real workspace
data.

## Context

Maverick currently has one complete agentic runtime backend, Codex, while hosted
model providers are limited to plain text generation. A model provider that can
emit function calls is not a Maverick runtime engine: it does not own platform
authorization, tool execution, confirmation, filesystem policy, recovery, or
audit.

The current persistence shape also mixes immutable session selection with
mutable provider conversation state. `RuntimeSessionRecord` carries both the
selected provider and `provider_thread_id`, and turns can still resolve the
workspace default. The provider control-plane store has no records for agentic
profile revisions, workspace bindings, or evidence-backed capability
certificates. The common document adapters support insert-if-absent, but do not
yet expose a matched compare-and-set result suitable for revision fencing.

The complete normative requirements are recorded in the workspace Storage
artifact `storage/generated/specs/maverick-agentic-multimodel-development-spec-2026-08-16.md`
(revision 2.1, SHA-256
`02bd09144de71d69d5888d5f68c57c285dbaf4848955e6f1ccbcdbab917597ce`).

## Decision

### 0. Remote agentic execution is contained before further parity work

Hosted agentic, Google agentic, and OpenRouter agentic switches default off.
Only the exact local Codex app-server identity is treated as local; every other
agentic provider identity, including an unknown future hosted provider, fails
closed. Even when all process flags are explicitly enabled, the Phase-0
attestation barrier rejects remote session creation and provider dispatch until
Phase 1 replaces that hard barrier with a revision-bound server proof. Client
data declarations, browser consent, and the legacy
`workspace_internal_fake` value cannot authorize a session.

Admission rejects a new remote execution binding before the session aggregate,
provider state, turn, thread, claim, prepared-session lock, or app-stream
reservation is persisted. API and app preflight carry one authorized governance
snapshot and immutable pin into creation. If the binding id, binding revision,
default selection, or complete immutable definition differs when the pin is
materialized, admission fails rather than silently authorizing one binding and
using another. Existing pinned remote sessions are rejected again at queue
admission and provider-start handoff. Browser and app requests cannot classify
session data; Core interprets neither an egress-policy id nor a persisted legacy
declaration as attestation. Ambiguous persisted sessions transition to
`recovery_required` through the serialized session lifecycle handoff, expose
only an allowlisted public reason, lose runtime bearer authority, and cannot
accept a new turn; this is quarantine support, not the Phase-2 recovery engine.

The operator containment service inventories all stores through their JSON or
Mongo abstraction. It correlates each ordered provider step with either a
persisted final output or one or more real ledger-backed proposals, reading the
complete immutable event archive across every page. A step with neither outcome
is ambiguous; aggregate request-minus-invocation arithmetic is not evidence.
The plan disables remote workspace bindings, suspends remote profile revisions,
revokes current remote suite-v8 certificates, and quarantines ambiguous
sessions. Dry-run is non-mutating and emits identities, revisions, counts,
per-target digests, and a whole-plan digest without credential or private
provider data.

Apply is a partially ordered saga, not a transaction and not an idempotent or
safe-to-retry command. Provider binding/profile/certificate status writes use
record revision CAS; session quarantine is a distinct serialized lifecycle
transition. A failure or CAS/lifecycle conflict can leave earlier targets
applied. The audit records structured partial counts and a safe failure code,
never claims success for an incomplete plan, and requires a new dry-run and
human review before any later apply. A successful apply also consumes its
reviewed digest and still requires a fresh dry-run for post-apply verification.
Phase 0 is not operationally complete; the gate remains
`live_apply_pending_review` until a separately approved apply and verification
occur.

### 1. Definitions and workspace bindings are separate

`AgenticProfileDefinition` is an immutable, installation-level provider-domain
record. It contains no workspace id, actor allowlist, default selection, or
workspace credential binding.

`WorkspaceAgenticProfileBinding` is a revisioned workspace-governance record.
It references an exact profile definition revision, an authorized credential
binding, a restrictive workspace policy, actor selection policy, egress policy,
and workspace-default state.

Mutable definition rollout state is stored separately from the immutable
definition. Workspace binding mutations require expected revision and cannot
rewrite existing runtime sessions.

### 2. Runtime selection has three state levels

Every new agentic session owns these distinct records:

1. `RuntimeExecutionBinding`, embedded in the session aggregate and inserted
   atomically with it. It is immutable and pins the exact engine, adapter,
   artifact digest, provider, model, protocol, routing constraint, credential
   reference, execution mode, policy ceilings, egress policy, and capability
   certificate evidence digest.
2. `RuntimeProviderState`, a private mutable record created with
   insert-if-absent after the session insert and updated only with expected
   revision plus turn-generation fencing.
3. `EffectiveRuntimeAuthority`, an ephemeral intersection recalculated at turn
   start and before every side effect. Only its HMAC digest and redaction-safe
   summary are persisted in audit data.

The session aggregate is initially persisted with
`preparation_status=unprepared`. It becomes executable only after provider
state revision zero (when a binding exists) and the initial runtime-state
snapshot have both been written, followed by a one-way `prepared` CAS on the
session. Exact creation retries complete missing writes with the original
preparation timestamp; conflicting retries fail closed. Both lifecycle
promotion to `running` and the provider-start handoff reject an unprepared
session, so a failure at any write boundary leaves a repairable,
non-executable aggregate.

Live certificate, credential, binding, workspace policy, actor/session grant,
tool policy, app mount, health, and revocation state may only reduce or block the
pinned ceiling. Authority expansion requires a new session or explicit fork
with a new execution binding.

An execution-authority change that is proven compatible uses a versioned
continuation fork; it never rewrites the predecessor binding. Core serializes
the fork with ordinary message admission, and queued, active, or waiting turns
on either side block it. Core creates a child session with the current binding
for the source profile and model, persists an idempotent handoff record,
CAS-fences the predecessor provider state, proves the predecessor process is
closed, transfers the provider thread and continuation ids to the child, and
rebinds the existing logical runtime thread to the child. Compatibility requires the same profile
identity, engine, adapter id/version, provider, model, protocol/API, routing,
credential reference, reasoning contract, execution mode, policy ceilings,
and egress policy. The target capability set may only be an intersection of
the predecessor and target certificates; it may never expand authority.
Legacy-inferred bindings, missing provider threads, revoked certificates, or
any unproven field require an explicit new conversation instead. Automatic
continuation forks are limited to `chat_root` sessions; hidden inter-agent and
system sessions require a separately designed ownership handoff rather than
silently changing their scheduler references.

Provider continuation state is transferred as an ownership unit, not merely as
an identifier. For Codex, the thread database stores an absolute rollout path,
so the executable child and its operating-system sandbox must use the
lineage-root `CODEX_HOME` as both `CODEX_HOME` and `HOME`. Core closes the
predecessor runtime before state transfer or child start, and independent
conversations never share that home. If the canonical lineage home is
unavailable, resume fails explicitly as `provider_thread_missing` and never
starts a replacement thread. Only confirmed missing-thread/rollout failures use
that classification; other app-server resume rejections remain
`provider_request_rejected`.

An interrupted handoff does not retain authority merely because its target was
valid when created. Before each resumed phase Core revalidates the source and
target certificates, live workspace binding and credential governance, current
adapter artifact digest, and persisted compatibility proof. It may finish an artifact-stale intermediate link only to
continue immediately through a bounded chain to the newest compatible
revision. A revoked or incompatible target is quarantined and fails closed.

The predecessor and child form one logical transcript lineage. REST,
WebSocket, transcript, usage, and cleanup surfaces traverse that lineage while
each event and turn remains owned by the immutable session under which it was
executed. The predecessor permanently rejects provider-state updates and new
turns after fencing. WebSocket snapshots declare both the originally requested
session id and the complete physical lineage so clients continue accepting
child events after a live rebind without weakening workspace authorization.

### 3. Capability certification is evidence-backed

Agentic availability is derived from an immutable `CapabilityCertificate` plus
a revisioned status record. A certificate identifies the exact runtime engine,
adapter version and artifact digest, provider, model/revision, protocol/API
version, certified upstreams, routing digest, capability set, suite version,
test run, evidence digest, issue time, and expiry.

Vendor capability flags are only onboarding prerequisites. They never grant
Maverick runtime authority. Expired, revoked, mismatched, or upstream-ineligible
certificates fail closed before provider execution and during live authority
recalculation.

Large evidence is written once to a platform-owned, content-addressed evidence
store. A certificate stores only immutable digests and opaque evidence ids.
Workspace Storage may receive an explicit redaction-safe export, but it is not
authoritative evidence.

Certification follows one trust sequence: deterministic conformance, an
operator-only synthetic live probe, behavioral conformance validation of the
complete ordered manifest and canonical command digests, then certificate
publication. Google and OpenRouter suite-v8 manifests contain both
`fixture_contract` and `live_probe`. Repository tests may explicitly select the
fixture step so normal CI sends no provider traffic, but an incomplete run is
rejected by signing, verification, and publication and can never become
certificate evidence.

### 4. Runtime adapters are asynchronous and provider-agnostic

`AgenticRuntimeEngineAdapter` owns async validate, prepare, execute, cancel,
recover, close, and health operations. Execution yields bounded, typed,
provider-neutral events. The adapter contract does not require a command,
process id, launch spec, or recovery command.

`LocalProcessRuntimeLifecycle` is an optional protocol for Codex and future
local runtimes. Common runtime code detects that protocol instead of branching
on `provider_id == "codex"`.

Raw provider payloads and protocol-private continuation state remain inside the
adapter/codec and private envelope services. Public runtime events never expose
them.

### 5. Existing control-plane registries are the only tool authority

The hosted runtime uses a `RuntimeToolOrchestrator` facade over the existing
core CLI and MCP registries, enabled-app mounting, dependency/interface
resolution, invocation policy, grants, and execution policy. It does not create
a second registry, invoke app modules directly, or specialize app ids.

Canonical handles are typed (`cli:`, `mcp:`, `app-interface:`, and
`core-capability:`). Provider-safe names map deterministically back to those
handles. Discovery does not imply invocation authority; every call is resolved
and authorized again immediately before execution.

### 6. Tool side effects are journaled before execution

Every provider tool proposal creates a `ToolInvocationRecord` before validation
or side effects. Private canonical arguments are encrypted behind a Core-issued
opaque locator. Public summaries are allowlisted and bounded, and the argument
digest is a domain-separated HMAC.

Mutating and destructive calls require a persisted one-shot
`ToolConfirmationGrant` when policy requires it. The grant is bound to actor,
session, turn, invocation, tool handle, argument digest, policy revision, and
expiry. It is atomically consumed before the invocation becomes authorized.

`executing` is persisted before crossing the side-effect boundary. After a
crash, an uncertain mutating/destructive call becomes `execution_unknown` and
is never replayed automatically. Read retries require an explicit safe-retry
contract. Browser state is not authoritative.

### 7. Provider-private state is bounded and opaque

Provider continuation ids and private envelopes are not part of the immutable
execution binding or ordinary session API. An envelope stores only a Core-issued
opaque locator, schema/codec/encryption versions, digest, size, and timestamp.

Private blobs use authenticated encryption with AAD binding workspace, session,
engine, adapter, codec, and schema. They are subject to per-record and
per-session quotas and explicit retention. Only the matching adapter and the
authorized recovery path may resolve them through the Core service. Codec,
digest, or version mismatch requires explicit recovery; no best-effort parsing
is allowed.

Thought signatures and similar protocol state are neither transcript content
nor analytics input and must not reach UI, ordinary logs, app hooks, or exports.

### 8. Remote-provider egress is decided per content block

Every system/developer instruction, user block, skill fragment, attachment,
app reference, tool schema, tool result, and provider-state block receives an
`EgressDecision` before it can leave Maverick. Decisions include destination,
data class, provenance, trust, policy revision, reason, transformation, and
domain-separated HMAC digests; they do not include source or transformed
content.

Unknown classification, provenance, trust, destination, or policy fails closed.
Current contained profile revisions list only Core-classified `public` content;
`workspace_internal_fake` is always denied by the egress evaluator even if a
malformed policy lists it. The historical `fake-data preview` display label is
retained verbatim as a warning, not an attestation or authority grant. In Phase
0 the independent central admission barrier authorizes no remote agentic
execution. Secrets, bearer authority, host operational metadata, unclassified
content, and client-supplied classification are never remotely exportable.

OpenRouter agentic routing pins certified upstreams, disables fallback, requires
parameters, denies data collection, and enforces ZDR when the egress policy
requires it. No eligible upstream means no request. Effective upstream drift is
verified against the certificate.

The contained OpenRouter candidate uses Chat Completions v1, DeepSeek V4
Flash, and the exact `deepinfra/fp8` endpoint. Request routing uses the endpoint
tag; response verification additionally requires OpenRouter's effective
provider identity and terminal router metadata before the continuation is
accepted as complete. The current contained definitions are Google revision 13
and OpenRouter revision 12, both bound to
`maverick-hosted-tool-loop==5`; older revisions are suspended rather than
overwritten. Their certification manifests retain the distinct deterministic
fixture and synthetic live steps. No live probe is run by ordinary repository
checks, and no fixture-only result is certificate evidence.

## Concrete persistence map

The first implementation uses the existing JSON/Mongo control-plane adapter
boundary and workspace runtime partitioning. Collection and file identities are
normative so both adapters implement the same semantics.

| Record | JSON/Mongo collection or runtime file | Identity and write rule |
|---|---|---|
| Profile definition | `providers/agentic_profile_definitions.json` / `provider_agentic_profile_definitions` | `(definition_id, revision)`, insert-only |
| Definition status | `providers/agentic_profile_definition_statuses.json` / `provider_agentic_profile_definition_statuses` | `(definition_id, definition_revision)`, revision CAS |
| Workspace binding | `providers/agentic_workspace_bindings.json` / `provider_agentic_workspace_bindings` | `binding_id`, workspace-scoped revision CAS; service enforces one enabled default per workspace/runtime context under the same collection lock/transaction |
| Capability certificate | `providers/agentic_capability_certificates.json` / `provider_agentic_capability_certificates` | `certificate_id`, insert-only |
| Certificate status | `providers/agentic_capability_certificate_statuses.json` / `provider_agentic_capability_certificate_statuses` | `certificate_id`, revision CAS |
| Evidence metadata | `providers/agentic_capability_evidence.json` / `provider_agentic_capability_evidence` | evidence digest, insert-only |
| Evidence blob | `data/control-plane/provider-evidence/<digest-prefix>/<digest>` or configured platform blob adapter | content-addressed, create-if-absent, digest verified |
| Execution binding / session lifecycle | `runtime/sessions/<session_id>/session.json` | binding embedded in a single immutable aggregate insert; `unprepared -> prepared` publication uses a one-way CAS, while lifecycle status transitions are serialized by `session_lifecycle_handoff` and are not provider-record CAS |
| Provider state | `runtime/sessions/<session_id>/provider_state.json` | `session_id`, insert-if-absent then revision/generation CAS |
| Continuation handoff | `runtime/continuation_handoffs.json` | one workspace-scoped record per predecessor session; immutable compatibility evidence plus monotonic phase/revision CAS |
| Tool invocation | `runtime/sessions/<session_id>/tool_invocations.json` | `invocation_id`, revision CAS |
| Confirmation grant | `runtime/sessions/<session_id>/tool_confirmation_grants.json` | `grant_id`, revision CAS and atomic active-to-consumed transition |
| Private blob metadata/content | `runtime/sessions/<session_id>/private/` behind the Core private-state service | Core-issued random locator, encrypted, create-if-absent, bounded |
| Egress decision | `runtime/sessions/<session_id>/egress_decisions.json` plus redaction-safe audit projection | `decision_id`, append/insert-only |

Runtime private files remain Core-owned operational state even though the local
adapter partitions them under the workspace runtime root. Ciphertext at rest is
not a capability; adapters and apps receive no locator-resolution surface.

## Atomicity, CAS, and fencing

The common document collection contract will add an atomic compare-and-set
operation that returns whether an exact identity-and-revision query matched.

- JSON performs the match and rewrite while holding its existing process file
  lock and in-process lock.
- MongoDB uses one conditional update and checks `matched_count`; unique indexes
  enforce immutable identities and insert-if-absent races.
- In-memory collections use the same match/update semantics under `RLock`.

Store services never emulate CAS with an unlocked read followed by write.
Revision starts at zero. Successful mutable writes increment by exactly one.
These record-CAS rules apply to provider definition status, workspace binding,
certificate status, provider state, and other explicitly revisioned records.
They do not turn the runtime-session lifecycle into a revisioned provider
record: session quarantine acquires the session lifecycle handoff, re-reads the
aggregate, validates the legal transition, and persists the new status under
that serialization boundary.
Late provider-state writes additionally match the current turn generation and
cannot change stopped, cancelled, failed, or recovery-required lifecycle state.
Continuation transfer first CAS-fences the predecessor provider-state revision;
all later ordinary provider-state updates reject that fence. Handoff phases are
monotonic and make recovery after any intermediate process failure idempotent.

Session aggregate creation remains one insert. No cross-collection transaction
is required. Provider-state initialization is the explicit second step and is
repairable only through idempotent insert-if-absent.

## Schema migration and rollback

The pinning migration is versioned and idempotent. It:

1. creates built-in Codex definition, status, certificate/preview status, and
   workspace binding records without raw credentials;
2. maps the authoritative workspace runtime selection to one binding;
3. embeds the maximum historically demonstrable execution binding in each
   agentic session;
4. moves provider thread state into provider-state revision zero;
5. marks ambiguous fields `legacy_inferred` and ambiguous sessions
   non-continuable instead of inventing values;
6. writes a migration journal and validates counts/digests before cutover.

The JSON adapter preserves a pre-migration backup through the existing
control-store migration/cleanup discipline. Mongo migration uses idempotent
upserts/inserts and an explicit journal. Rollback restores the former schema
before the runtime reader cutover; after reader cutover, rollback may disable
the feature and preserve pinned records, but must not dual-write or silently
reconstruct the legacy default-based runtime path.

`/api/providers/active` becomes a projection of the workspace-default agentic
binding when the pinning reader cutover occurs. Chat session selection never
mutates that projection. All repository consumers are migrated in the same
feature, and the legacy runtime reader is removed before Definition of Done.

Runtime session projections carry the authoritative public governance snapshot
needed to render historical pins: the exact immutable display name, provider,
model, endpoint and upstream destination, effective egress/data policy, current
certificate posture, and containment state. Chat renders those fields without
reconstructing policy or classification in the browser. A contained historical
pin remains visible as `fake-data preview` and NO-GO but never becomes a
selectable new-chat option.

## Failure semantics

- Missing or invalid profile, binding, certificate, credential, adapter,
  provider state, classification, destination, or tool authority fails closed.
- A certificate or credential revocation immediately narrows existing sessions
  without rewriting their execution binding.
- Provider request retries are forbidden after acceptance unless a certified
  provider idempotency/retrieval contract proves safety. Ambiguity enters
  recovery-required state.
- Provider-state CAS conflict discards the late write and triggers
  reconciliation; it never overwrites newer continuation data.
- Mutating/destructive tool ambiguity becomes `execution_unknown`.
- Private-state corruption or quota exhaustion is explicit and never degrades
  to an incomplete vendor history.
- Feature flags can stop new sessions and live-narrow existing authority, but
  cannot migrate an existing session to another engine/model/upstream.
- Turn admission validates live adapter/certificate authority before persisting
  a user or backend-recovery turn. A compatible mismatch completes the audited
  continuation fork; an incompatible mismatch returns
  `runtime_profile_upgrade_required` without queuing provider work.
- The admin-only continuation-repair command defaults to dry-run. Inventory
  resolves requested roots and predecessors to their current lineage tips. A
  mutating run snapshots the provider control plane, workspace runtime indexes,
  every selected lineage session's JSON/event-history records, and the Codex
  lineage-root SQLite/rollout conversation store before applying the exact
  preflight-compatible scope. SQLite uses an online checked backup; rollout
  files are canonical, bounded, checksummed copies. Unrelated homes and runtime
  caches are not copied.

## Runtime bearer authority interaction

Runtime bearer validity remains necessary but insufficient authority. The
hosted runtime and tool orchestrator must bind every operation to the persisted
session, workspace, actor, execution mode, execution binding, current grants,
and current invocation policy. Client/model payloads cannot supply profile,
credential, owner, grant, tool authority, private locator, or policy fields.
Every runtime-token validation also re-reads its owning session; a missing or
`recovery_required` owner has no operational bearer authority even if the token
record is still cryptographically valid and marked active.

Until the open runtime bearer authority, CSRF, app WebSocket, frontend/backend
isolation, and recovery-policy blockers in `SECURITY.md` are closed:

- every remote agentic profile is contained and non-selectable (NO-GO);
- no browser consent or fake-data declaration can activate remote agentic work;
- certificate evidence proves adapter behavior, not platform production safety;
- UI and API status must expose the preview limitation;
- no certificate or feature flag may claim production readiness.

### Operational feature flags

The agentic rollout has independent process-level kill switches. Existing
profile and execution-binding records are never rewritten when a switch is
changed; authoritative runtime boundaries re-evaluate the applicable switches
to provide live narrowing for already-pinned sessions.

| Surface | Environment variable | Default |
|---|---|---|
| Profile definitions and workspace bindings | `MAVERICK_FEATURE_AGENTIC_PROFILES` | enabled |
| Agentic adapter contract | `MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT` | enabled |
| Hosted agent runtime | `MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME` | **disabled** |
| Tool confirmation and resume | `MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION` | enabled |
| Provider-private state | `MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE` | enabled |
| Egress enforcement | `MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT` | enabled |
| Google agentic preview | `MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW` | **disabled** |
| OpenRouter agentic preview | `MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW` | **disabled** |
| Parallel tool calls | `MAVERICK_FEATURE_PARALLEL_TOOL_CALLS` | disabled |

Values `0`, `false`, `no`, and `off` disable a surface. Values `1`, `true`,
`yes`, and `on` enable its switch. An absent value uses the declared default;
an invalid configured value fails closed. Remote flags do not bypass the
independent Phase-0 attestation barrier. Disabling egress enforcement blocks hosted export rather than
bypassing evaluation. Enabling the parallel-tool-call switch does not override
the MVP's sequential policy ceilings or codec rejection; it only reserves an
independent rollout control for a future implementation.

## Implementation sequence

The accepted order is:

1. pin Codex sessions with no functional change;
2. introduce the async adapter contract and optional local lifecycle;
3. add certificates and effective-authority narrowing;
4. add governed tool orchestration and persistent confirmation/replay state;
5. add egress and provider-private state;
6. prove the hosted loop with deterministic fixture adapters/providers;
7. define one current GA provider candidate while retaining the exact
   `fake-data preview` warning label;
8. expose binding/certificate/session controls in Settings and Chat;
9. add OpenRouter fixed-upstream privacy routing;
10. complete concurrency, recovery, leakage, sub-agent, and rollback hardening.

Every phase has focused tests and a checkpoint commit. A later phase cannot
weaken an earlier boundary.

Execution status and remaining preview gates are tracked in
`docs/product/agentic_multimodel_tasklist.md`. Signed evidence creation and its
handoff to the certificate publisher follow
`docs/runbooks/agentic_certification_evidence.md`; provider activation and
rollback then follow `docs/runbooks/agentic_provider_preview.md`.

The phase-9 gate covers cancellation races, terminal provider outages,
mid-session certificate revocation, live egress-policy drift, prompt injection,
provider-private quota/integrity failure, confirmation replay, child-agent
binding isolation, and an operator rollback runbook. It does not promote either
remote profile beyond the contained preview.

## Consequences

- Codex remains supported, but becomes one adapter with an optional local
  process lifecycle rather than a generic runtime special case.
- Hosted models can become complete Maverick runtimes without owning platform
  tool execution or credentials.
- More records and explicit state transitions are required, but session
  behavior becomes deterministic under default changes, revocation, crashes,
  retries, and recovery.
- Control-plane and runtime stores gain real CAS semantics shared by JSON,
  MongoDB, and tests.
- Remote agentic execution remains NO-GO while local Codex and plain hosted
  text retain their existing behavior; reopening requires the later attestation
  and recovery gates, not a browser declaration or a flag alone.
