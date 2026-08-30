# ADR-0010: Agentic Multimodel Runtime Boundaries

## Status

Accepted on 2026-08-16 as the ADR-0 gate for the agentic multimodel runtime.

Phase-0 containment was accepted on 2026-08-25 and materially closed on
2026-08-26. The Phase-1 security-boundary amendment was implemented on the same
date: revision-bound server attestation, resource-derived classification,
certified schemas/TCB, fd-relative confinement, and one effective-capability
snapshot now exist. The Phase-2 journal/recovery amendment was implemented on
2026-08-27: every provider call is durably accounted, provider state is staged
until reconstructible pairing and commit, and recovery is connected to the
productive lifecycle.
The Phase-3 finalization amendment was implemented on 2026-08-27: provider-step
and tool-call budgets are separate and restart-safe, two terminal attempts keep
step/output/cost/deadline reserves, final requests are tool-less, and an
unexpected finalization call has exactly one denied-and-paired recovery.
The 2026-08-28 review amendments make terminal egress request-transactional,
cover complete terminal projections in the cost reserve, deadline-fence both
synchronous tool execution and slow result persistence, make the terminal
success CAS conditional on a persisted live execution lease, and keep
OpenRouter finalization instructions request-scoped.
Remote agentic execution nevertheless remains **NO-GO**:
the availability flag is false and no remote profile, binding, certificate,
behavioral evidence, canary, or production gate is enabled. Codex agentic and
plain hosted text are not contained or reclassified as hosted remote.

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
closed. Even when all process flags are explicitly enabled, the independent
availability barrier rejects remote session creation and provider dispatch
until a later release explicitly admits the Phase-1 revision-bound server
proof. Client data declarations, browser consent, and the legacy
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
accept a new turn. Phase 2 now supplies the recovery engine behind that
quarantine boundary; it does not make a remote profile available.

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
The material Phase-0 operation is recorded by source revision
`69d9e10fea641f805c1c52801b7fd60a027b02f9`, reviewed plan digest
`02484a30f9ea7254c5deebd69e5af4416a22d8aecc006d81b7b5d6aad9c4578d`,
audit saga `4a6ab3ee-8b55-40c4-9dd6-2eba17bd9bdc`, apply artifact SHA-256
`5cd77cf01ab3e4ed12ca0ab76d3774dadf0482bd892821fb8883ef3cb2ab6898`,
post-apply zero-target digest
`56253919e93461e67b62a068e6e8718638475d05173dfff97b2912dcbeed2e77`,
and post-apply artifact SHA-256
`c6daa0b542edc92ef09116b323b1b024d3d1f94ef53aa85344eb55ea4aad733c`.
These facts close material containment only; they do not claim remote release,
certification, migration approval, canary, or production completion.

### 0A. Phase-1 authority is server-owned and code-bound

A workspace fake-data attestation is a dedicated CAS record with workspace,
actor, declaration, scope, timestamps, revision, and revocation. Only governed
operator/admin Core surfaces mutate it; Settings and Chat receive a read-only,
redaction-safe projection. It is distinct from the effective classification of
each exact resource/version and from the final per-block egress decision. A
declaration can narrow authority but never promote real, secret,
workspace-internal, or unclassified data. Client declarations, UI labels,
feature flags, egress-policy ids, and legacy `declared_remote_data_class` are
not attestations and are not propagated to continuation requests.

Every provider input source carries canonical provenance, trust, data class,
resource identity/revision/digest when applicable, and a restrictive join.
Missing or inconsistent classification becomes `unclassified`. The effective
authority used by admission, continuation, request building, catalogs, API,
Chat, and Settings is one intersection of certificate, profile ceiling,
workspace binding, actor policy, live authority, feature flags, and provider
health. Unsupported skills, modalities, references, tool surfaces, and writes
fail with allowlisted reason codes before persistence or egress.

The certified execution TCB is one deterministic code-owned manifest. It covers
all authority-changing Core and UI surfaces and is the sole source for suite,
artifact, signing/publication, execution-binding, and live-status digests. The
publisher recomputes the digest; drift or missing legacy identity makes a
remote certificate ineligible before create, continuation, refresh, or
dispatch. Manifest version 5 also declares six maintained dependency contracts
for runtime admission, provider-input composition, classification/egress, tool
execution, provider-state/lifecycle, and served governance. Core statically
walks each declared local import closure, including package initializers, the
exact `core/inter_agent/generalist_context.py` projection closure,
continuation/recovery, app-entrypoint, observability, and usage dependencies.
Every reached dependency must already be in the canonical artifact set; a new
uncovered callout makes TCB identity calculation fail closed rather than
silently producing a certifiable digest. This implementation boundary does not
itself make remote execution available.

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
adapter version and artifact digest, certified execution TCB manifest/digest,
provider, model/revision, protocol/API version, certified upstreams, routing
digest, capability set, suite version, test run, evidence digest, issue time,
and expiry.

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
publication. Google and OpenRouter suite-v16 manifests contain both
`fixture_contract` and `live_probe`. Repository tests may explicitly select the
fixture step so normal CI sends no provider traffic, but an incomplete run is
rejected by signing, verification, and publication and can never become
certificate evidence. Every stage recomputes the live TCB digest instead of
accepting one supplied by a caller.

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

A provider-visible tool schema is public only when its surface is Core-owned,
explicitly declared public, and included by the exact certified TCB. App-owned,
dynamic CLI/MCP, omitted, and otherwise uncertified schemas fail closed before
request egress. The catalog retains a bounded structured rejection with an
allowlisted reason code; it never silently drops an unsupported requested
surface.

Core filesystem read, list, write, and shell-cwd admission use a pinned
workspace-root descriptor. Each component is opened relative to an already
verified descriptor with no-follow/directory flags where the platform provides
them; verified resources are not reopened by pathname. Identity/version-bound
chunks and cursors reject mutation, UTF-8 chunks never split a code point,
binary chunks use bounded base64, and listing never descends into `.git`.
Final/parent symlinks, root or directory
rename/swap, and validation/use races fail closed for reads, lists, writes, and
shell cwd. The same exact observation supplies resource-derived classification.

Every mutating provider schema requires the applicable root-to-target
`AGENTS.md` digest. File writes, edits, patches, moves, and deletes revalidate
that exact snapshot immediately before commit and immediately after it; a
post-commit mismatch is rolled back before success can be reported. Shell and
managed-process launch revalidate immediately before `exec`. Missing digests
are invalid arguments rather than an instruction snapshot inferred on behalf
of the model.

Shell and managed-process writes remain in a private overlay until Core has
validated the complete diff. Newly-created directories and every other
unrepresentable effect are rejected explicitly. The upper scan includes the
overlay root plus file/directory mode, owner, timestamps, and bounded xattrs.
Ordinary xattr changes, explicit timestamp changes, and root metadata changes
are rejected. Content-only replacement stages an exact clone of the existing
mode, ownership, ACL/xattr set, while representable new-file creation metadata
is applied explicitly. Representable text files are staged as one
descriptor-confined batch with retained pre-images; a late
instruction race or file failure rolls back every already-applied entry in
reverse order. Terminal `process.status` performs that commit and is therefore
classified as mutating and non-retry-safe rather than as a read.

### 6. Tool side effects are journaled before execution

Every decoded provider tool proposal creates a preliminary
`ToolInvocationRecord` before catalog resolution, policy/budget disposition,
schema validation, or side effects. Its resolved handle is nullable. The
immutable identity retains the provider-safe name, call id, request id, stream
ordinal/index, policy revision, and authority digest. Private canonical or
malformed raw arguments are encrypted behind a Core-issued opaque locator;
public summaries are allowlisted and bounded, and the argument digest is a
domain-separated HMAC. Exact replay deduplicates, while a reused call id with a
different name or argument digest fails closed.

The preliminary row is the first WAL half and points at a deterministic
request-scoped private locator; encrypted argument persistence is the second
idempotent half. A crash between them therefore leaves a countable proposal
that an exact replay can repair, never an unjournaled effect candidate.

Unknown, revoked, not-authorized, schema-denied, budget-denied, and
parallel-denied calls receive durable dispositions and denial results rather
than disappearing. Google and OpenRouter retain all indexed calls and calls
decoded before a later terminal stream error. Parallel execution remains
disabled: when a provider emits multiple calls, Core persists and emits every
proposal before denying and pairing every call.

Mutating and destructive calls require a persisted one-shot
`ToolConfirmationGrant` when policy requires it. The grant is bound to actor,
session, turn, invocation, tool handle, argument digest, policy revision, and
expiry. It is atomically consumed before the invocation becomes authorized.

`executing` is persisted before crossing the side-effect boundary. After a
crash, an uncertain mutating/destructive call becomes `execution_unknown` and
is never replayed automatically. Read retries require an explicit safe-retry
contract. The live event order is proposal persisted, `proposed`, validation
and disposition, `started`, effect boundary, result persisted, then
`completed`/`failed`; browser state is not authoritative.

### 7. Provider-private state is bounded and opaque

Provider continuation ids and private envelopes are not part of the immutable
execution binding or ordinary session API. An envelope stores only a Core-issued
opaque locator, schema/codec/encryption versions, digest, size, and timestamp.

Private blobs use authenticated encryption with AAD binding workspace, session,
engine, adapter, codec, and schema. The provider-state envelope additionally
retains only redaction-safe source block digests, source data classes/trust
levels, their restrictive effective join, codec identity, provider request id,
and turn generation. The joined class is never assumed fake, public, or
trusted-platform. Private content and credentials remain inside the encrypted
blob and are absent from APIs and audits. Blobs are subject to per-record and
per-session quotas and explicit retention. Only the matching adapter and the
authorized recovery path may resolve them through the Core service. Codec,
digest, or version mismatch requires explicit recovery; no best-effort parsing
is allowed.

Provider response bytes are first written as staged state under a deterministic
request-scoped private locator. A `ProviderStepJournalRecord` attaches that
envelope by revision CAS, but ordinary continuation reads still see only the
last committed `RuntimeProviderState`. Core promotes the exact staged envelope
only after either a validated final response or a complete ordered proposal,
disposition, result/denial, and reconstructible pairing. Provider-state CAS is
followed by journal commit; a crash between those records is repaired by the
saga and never makes an unrelated staged blob authoritative.

Thought signatures and similar protocol state are neither transcript content
nor analytics input and must not reach UI, ordinary logs, app hooks, or exports.

### 7A. Provider steps are a persistent recovery saga

Each outbound step owns a schema-versioned journal row containing the request
and response ids, acceptance, pinned engine/adapter/provider/protocol/API and
codec identity, base provider-state revision/digest, staged private reference,
ordered proposal/disposition/result ids, pairing source/status, immutable
request-input lineage digest, private final-output outbox identity and delivery
status, immutable request phase/control digest/output/input/cost reservation,
tool-budget charges, paired-result byte count, provider usage, commit status,
timestamps, and revision. JSON and document stores use the same
insert-if-absent and compare-and-set transitions. Tool ledger, private blob,
provider state, and journal remain distinct stores: ordered WAL repair is
explicit and no cross-collection transaction is simulated.

Recovery runs at backend startup/worker loss, continuation pre-admission,
hosted pre-prepare, uncertain cancellation, execution failure, and explicit
adapter recovery. It uses only the pinned binding and exact current codec;
Google and OpenRouter inspectors decode redaction-safe pending/consumed call
identities rather than migrating vendor state. Recovery may repair an orphan
proposal or staged-blob attachment, materialize a pre-effect denial/result,
finish pairing, promote the exact envelope, commit, or consume a pairing only
when persisted evidence proves that transition. An explicit provider terminal
with no staged state or observed call may return to the last commit.

An accepted transport with insufficient evidence, codec/binding mismatch,
incoherent pairing, consumed pairing without a committed child, or ambiguous
effect instead moves the journal and session by CAS to `recovery_required`.
Containment first retries the authoritative session CAS from a fresh read, then
independently retries journal quarantine. The public cause is allowlisted;
bounded arbitrary diagnostic detail is encrypted, Core-owned, and best-effort.
Private-payload, audit, projection, or journal-CAS failure cannot precede or
cancel a successful session quarantine. Restarting any terminal recovery
transition is idempotent. Queue, continuation, prepare/dispatch, and
runtime-token paths read the persisted WAL and deny quarantined or unresolved
sessions.

A ready pairing is owned by exactly one active original turn. Continuation
requires the source journal id, source turn and provider request identities,
current private-state request/generation, and exact non-tool input lineage to
match. A normal new user turn cannot claim or migrate it. If any terminal
limit, cancellation, authority/certificate revocation, egress denial, or
execution failure leaves such a pairing, same-turn recovery must seal it or the
session is quarantined before ordinary work resumes.

Final text is encrypted in a deterministic Core-private outbox and its
identity, digest, and size are attached before stream completion and journal
commit. The two terminal events have stable identities and separate durable
acknowledgements. A crash after commit replays the same output without another
provider request; an unprovable identity quarantines rather than regenerates.
The journal and unauthorized APIs never contain the final text.

### 7B. Finalization capacity is reserved rather than hoped for

Hosted turns account provider requests separately from provider tool
proposals. The adapter pins an exploration output ceiling and a terminal
per-attempt output, micro-USD, and deadline reserve. Core protects one normal
finalization request and at most one recovery request. A live policy can only
tighten the turn; it may not consume already protected steps, output, cost, or
time. Journal schema v4 makes request reservations, usage replacement, tool
charges, and paired-result bytes reconstructible after restart. Missing usage
keeps the conservative reservation. An in-budget proposal and its tool charge
share one journal CAS; provider usage is durable before its public usage event. A
terminal request whose certified cost ceiling exceeds its per-attempt
allocation is rejected before transport. Per-attempt allocations cover the
provider estimator for a complete terminal request at the hosted input ceiling,
including retained context, provider-private state, and admitted tool results.

Before catalog materialization, Core rechecks effective admission and credential
availability. Per-block projection then stages deterministic egress decisions
without persisting or auditing them. The provider-specific request estimate must
fit before those decisions, the request journal, or transport are committed. An
exploration candidate that crosses the reserve is discarded and replaced by a
tool-less finalization candidate. Exploration also stops when its tool budget is
empty or another resource reaches the terminal reserve. The next normalized
request has phase `finalization`, an empty catalog, and an exact trusted Core
instruction placed after all other content. Google omits `tools`; OpenRouter
sends `tools: []` and `tool_choice: none`, and excludes that request-scoped
instruction from durable history. Both codecs reject a non-empty final catalog,
missing/modified instruction, or incoherent phase before transport.

Synchronous tool surfaces execute behind a pre-terminal deadline and
cancellation fence. Timeout CAS-publishes a deterministic failed read result
directly in the invocation ledger before any optional private-payload I/O; a
unique lease id and UTC expiry are persisted with `executing`, and `succeeded`
requires revision, lease, and unexpired-deadline predicates in the same
collection CAS. JSON evaluates the deadline while holding the collection lock
and rechecks it immediately before atomic replacement; Mongo evaluates it with
server `$$NOW`. A worker paused after its last cooperative check therefore
cannot commit success after expiry even if the timeout CAS is delayed.
Non-read effects that cross the boundary remain `execution_unknown` rather than
being paired as safe completion. Core shell/process surfaces register
cancellation cleanup with the lease before returning. The external signal and
COW commit share one linearization gate, so cancellation that wins cannot be
relayed by later polling into a post-cancel commit. Cancellation kills the full
process group, discards the overlay, and requested provider termination waits
for bounded worker quiescence. The adapter owns the managed-process registry;
session close, explicit session termination, and idle reap finalize its live map,
capture descriptors, overlays, global process registration, and durable status.

An empty or whitespace-only provider final is an explicit invalid outcome, not
a successful turn: its staged state is rolled back to the previous commit and
the public failure is structured. If the provider calls a tool despite the
closed catalog, Core first journals the proposal, persists a `budget_denied`
result, commits its pairing, and sends one tool-less
`finalization_recovery`. A second call is likewise denied but no additional
provider request is permitted; the unconsumed pairing is quarantined as
`recovery_required`. Thus every healthy terminal path contains non-whitespace
output, while every unhealthy path contains a visible failure and either a
continuable last commit or explicit quarantine.
Finalization phase chains are validated per original turn, so a completed turn
cannot prevent the next turn from beginning ordinary exploration.

### 7C. Provider input is compiled from a versioned semantic envelope

Core materializes every hosted request into semantic-envelope schema v1 before
egress or provider rendering. Blocks retain their distinct role, provenance,
content type, classification, source identity/revision, and SHA-256 source
digest. The envelope always includes the platform instruction, pinned runtime
identity, effective capability projection, applicable root-to-workdir
`AGENTS.md` chain, agent instruction, user/governed inputs, invoked skill
instructions, tool schemas/results, and applicable provider-private state.
Attachment, app-reference, and orchestration inputs are never flattened into an
unattributed prompt.

The classification attached to a semantic block must also match the digest of
its exact canonical projected bytes. Composite content is derived only by a
restrictive join over every independently classified component. Attachment
metadata is admitted separately from the referenced file and joined with it;
an attachment-only turn omits the absent empty prompt. Skills project the
complete descriptor-read `SKILL.md` and do not splice unbound catalog or
`state.json` name/description fields into the file classification. Any digest
or derivation mismatch becomes `unclassified` before egress.

App-reference classification has two independent inputs: admission of the
rendered metadata and an exact resource observation of the server-materialized
reference. Production bootstrap always wires the resource resolver to the
workspace classification store. Its app/entity key is stable while its
revision/digest commits to the complete materialized payload; no matching
record means `unclassified`, never an inferred `public` class.

`AGENTS.md` and `SKILL.md` reads are descriptor-confined, bounded, complete,
UTF-8 validated, and fenced to one resource identity/revision across chunks.
The chain is recomputed on every provider step, so continuation, recovery, and
post-compaction requests re-inject the current applicable instructions instead
of trusting an opaque provider history. A missing, escaped, mutated, oversized,
or otherwise non-projectable mandatory source fails before provider dispatch.

The immutable source snapshot has its own digest. The versioned hosted
projection compiler records a second digest over the exact destination
protocol, phase, roles, tool/result identities, transformations, egress
decisions, and exported-content digests. Both digests and compiler identity are
persisted in provider-step journal schema v4 and emitted only as redaction-safe
request evidence. Provider wire codecs remain deterministic TCB components;
changing their rendering changes the hosted adapter artifact and requires a
new immutable profile revision.

### 7D. Context and provider behavior are recipe-bound

Every hosted full-workspace definition pins an execution family, harness recipe
id/revision/digest, provider-capability catalog digest, semantic compiler,
tool-contract revision, and context policy. The same identities must match the
certificate, immutable session binding, runtime registry, effective authority,
and provider/model/protocol/API/endpoint/upstream/reasoning composition. Shared
loop construction selects this data-only recipe; it contains no Google or
OpenRouter model branch.

Context policy `p4-context-v4` reserves capacity independently of ordinary turn
budgets. At a deterministic threshold, the exact recipe compactor replaces old
provider history with a bounded extractive semantic summary of user constraints,
assistant decisions, tool actions including canonical arguments, and tool
outcomes. It retains every semantic event when the byte budget permits instead
of imposing an item-count window; actual byte-pressure clipping is distributed,
keeps both ends, and is explicitly marked with source size/digest. If even the
bounded per-event representation cannot fit, compaction fails instead of
deleting a middle event. Encrypted state classification, provenance, authority
digest, request/turn identity, and every call/result relation still active in
the current turn are preserved. Google uses
Core-managed stateless history; OpenRouter retains client-managed chat history
and replaces request-scoped system/developer authority with the current
projection on every continuation.
Compaction evidence and the endpoint snapshot digest enter the request-control
digest and provider-step journal without exposing raw history.
The reserve check uses the complete prepared request. When history alone is
below the normal trigger but the current request would exceed the usable
window, Core forces that same recipe compactor once, rebuilds the staged
request, and validates once more; it never loops or transports an oversized
candidate.

Tool output that cannot safely remain inline is retained as an immutable,
session/workspace-owned artifact. The provider receives only a bounded summary,
digest, byte count, and `artifact.read` reference. The complete serialized
projection, including adversarially long field names, is hard-capped by the
profile's `tool_result_summary_bytes`; accounting charges the original result
size. The semantic digest is bound to the exact artifact-reference projection
shown to the provider, while its class/trust/identity retain the original
result taint. An explicit `artifact.read` response is already a bounded byte
window and therefore bypasses generic result re-compaction, preventing
recursive artifact references while retaining its independent 64-KiB chunk
cap. Attachments
likewise remain distinct classified blocks
and are projected as explicit workspace-relative references that require live
filesystem-read authority. The reference declares `utf-8` for textual MIME and
`base64` for every other accepted MIME, matching the live tool schema. Neither
payload type is silently flattened or dropped. Codex retains its native same-turn steering path; hosted recipes that
cannot prove provider-native steering return an explicit `safe_next_turn`
fallback.

Immediately before a completion transport, Core performs the recipe-specific
preflight while egress decisions are still staged. Google fetches and validates
the official live Interactions OpenAPI operation plus the authenticated exact
model record, including streaming, usage, function tools, reasoning, and token
limits; it also verifies the exact wire shape and omits tools on final requests.
OpenRouter verifies the exact
wire shape plus fresh model and ZDR endpoint records, including FP8 identity,
all translated parameters, `tool_choice:none`, completion capacity, and total
input-plus-output context capacity. Failed or incoherent preflight commits no
content egress and sends no completion request.

### 8. Remote-provider egress is decided per content block

Every system/developer instruction, user block, skill fragment, attachment,
app reference, tool schema, tool result, and provider-state block receives an
`EgressDecision` before it can leave Maverick. Decisions include destination,
data class, provenance, trust, policy revision, reason, transformation, and
domain-separated HMAC digests; they do not include source or transformed
content.

Prompt, orchestration, skill, attachment, app reference, filesystem/tool
result, and provider-private sources keep distinct provenance. Filesystem and
resource-returning tool classification comes from the exact resource identity,
revision, and digest observed by Core. Transient prompt, agent-instruction, and
governed-context blocks receive a canonical classification only from a trusted
server-owned admission resolver bound to their exact workspace/session/turn,
source identity and digest. Hashing the bytes and recognizing a Core composer
id establish integrity, not a data class. Production bootstrap resolves prompt,
agent-instruction, and reference-metadata classes through the Core content
classifier and atomically persists their exact digest-bound entries in one
immutable turn manifest. Governed context cannot use one aggregate promotion:
the same writer classifies its exact control, summary, task/result, and artifact
chunks, which are restrictively joined and forced to untrusted trust. Unknown
identities or missing source evidence remain `unclassified`. For tool results, resource reads
keep exact observed taint and edit/patch diffs inherit their pre-image taint.
Shell/process streams and CLI/MCP discovery/results remain complete through the
shared compactor and are classified from their exact bytes. A remotely denied
private result remains in the ledger while a public call-paired error preserves
the next request's tool protocol. Shell/process operations with workspace
mutation scopes and mutating/destructive CLI/MCP definitions are denied before
their handler while no pre-effect result guarantee exists. App surfaces remain
discoverable, but app declarations cannot promote their result. Model or browser
declarations, generic hashing, and redaction cannot select, infer, or widen a
class. A missing or incoherent source classification produces `unclassified`,
and the restrictive join prevents an attestation or less-sensitive sibling
block from promoting it.

Unknown classification, provenance, trust, destination, or policy fails closed.
`workspace_internal_fake` is eligible for evaluation only when the exact
resource/version was independently classified as such by Core, an active
workspace-matching attestation covers that resource, and the selected policy
explicitly allows the class and destination. The attestation cannot create or
promote the resource classification. Current contained profile revisions list
only Core-classified `public` content, remain disabled and non-selectable, and
the independent central availability barrier still makes remote agentic
execution NO-GO. The historical `fake-data preview` display label is retained
verbatim as a warning, not an attestation or authority grant. Secrets, bearer
authority, host operational metadata, unclassified content, and client-supplied
classification are never remotely exportable.

OpenRouter agentic routing pins certified upstreams, disables fallback, requires
parameters, denies data collection, and enforces ZDR when the egress policy
requires it. No eligible upstream means no request. Effective upstream drift is
verified against the certificate.

The contained OpenRouter candidate uses Chat Completions v1, DeepSeek V4
Flash, and the exact `deepinfra/fp8` endpoint. Request routing uses the endpoint
tag; response verification additionally requires OpenRouter's effective
provider identity and terminal router metadata before the continuation is
accepted as complete. The current contained definitions are Google revision 30
and OpenRouter revision 29, both bound to
`maverick-hosted-tool-loop==22`; older revisions are suspended rather than
overwritten. Their certification manifests retain distinct deterministic
fixture and synthetic live steps. No live probe is run by ordinary repository
checks, and no fixture-only result is certificate evidence.

These adversarial-review definitions are governed-workspace candidates, not
Full Workspace claims. `codex-baseline-v10` now requires a live result behavior
probe rather than a mode string; the current probe deliberately fails for
mutating shell/process and app CLI/MCP scenarios. The profiles therefore pin
`hosted-governed-result-v1` and leave `full_workspace_contract_revision` empty.
Adapter 22, recipe revision 9, context-compaction schema 3, suite 26, and TCB
manifest v16 retain the composite-classification and rollback-safe multi-file
invariants.

Every existing pre-image stays descriptor-pinned across exchange and is checked
against its complete metadata/xattr snapshot, so a later-file metadata race
rolls back earlier writes without deleting the concurrent change. Content
effects carry exact atime/mtime; directory/root-only metadata and hardlink
effects that cannot be reproduced are rejected. Production input capture
content-classifies exact prompt/instruction/reference bytes and every governed
source chunk into one immutable turn manifest. Read-only variable tool results
are content-classified and remain provider-pairable; denied bytes stay private
behind a public error, while unguaranteed mutations are denied before execution.
Cancellation awaits all synchronous workers, and explicit process cleanup
signals known leaders before bounded post-SIGTERM orphan sweeps. The definitions
remain uncertified, unbound, unavailable, and independently blocked by Phase-0
admission; implementation completion is not provider evidence or release
approval.

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
| Workspace data attestation | `workspaces/data_attestations.json` / `workspace_data_attestations` | workspace id, revision CAS; actor/scope/timestamps/revocation required |
| Resource classification | `workspaces/resource_classifications.json` / `workspace_resource_classifications` | classification id plus exact workspace/resource identity/revision/digest, revision CAS |
| Data-governance audit | `workspaces/data_governance_audits.json` / `workspace_data_governance_audits` | audit id, append-only redaction-safe mutation fact |
| Execution binding / session lifecycle | `runtime/sessions/<session_id>/session.json` | binding embedded in a single immutable aggregate insert; `unprepared -> prepared` publication uses a one-way CAS, while lifecycle status transitions are serialized by `session_lifecycle_handoff` and are not provider-record CAS |
| Provider state | `runtime/sessions/<session_id>/provider_state.json` | `session_id`, insert-if-absent then revision/generation CAS |
| Continuation handoff | `runtime/continuation_handoffs.json` | one workspace-scoped record per predecessor session; immutable compatibility evidence plus monotonic phase/revision CAS |
| Tool invocation | `runtime/sessions/<session_id>/tool_invocations.json` | `invocation_id`, revision CAS; hosted `executing` records persist a lease id and UTC expiry, and success also requires that live lease in the atomic CAS |
| Confirmation grant | `runtime/sessions/<session_id>/tool_confirmation_grants.json` | `grant_id`, revision CAS and atomic active-to-consumed transition |
| Private blob metadata/content | `runtime/sessions/<session_id>/private/` behind the Core private-state service | Core-issued random locator, encrypted, create-if-absent, bounded |
| Egress decision | `runtime/sessions/<session_id>/egress_decisions.json` plus redaction-safe audit projection | `decision_id`, append/insert-only |

Runtime private files remain Core-owned operational state even though the local
adapter partitions them under the workspace runtime root. Ciphertext at rest is
not a capability; adapters and apps receive no locator-resolution surface.

## Atomicity, CAS, and fencing

The common document collection contract provides atomic compare-and-set
operations that report whether an exact identity-and-revision query matched,
including a deadline-aware variant for hosted tool-result commits.

- JSON performs the match and rewrite while holding its existing process file
  lock and in-process lock; deadline CAS rechecks immediately before atomic
  file replacement.
- MongoDB uses one conditional update, server `$$NOW`, and `matched_count`;
  unique indexes enforce immutable identities and insert-if-absent races.
- In-memory collections evaluate the same match/deadline/update semantics under
  `RLock`.

Store services never emulate CAS with an unlocked read followed by write.
Revision starts at zero. Successful mutable writes increment by exactly one.
These record-CAS rules apply to provider definition status, workspace binding,
certificate status, workspace attestation/classification, provider state, and
other explicitly revisioned records.
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
- Explicit provider `cancelled`, `budget_exceeded`, or `incomplete` terminal
  state can roll back only when the journal proves that no call or staged state
  exists; transport or codec failure after acceptance remains ambiguous.
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

The canonical effective snapshot is the restrictive intersection of the
capability certificate, profile policy ceiling, workspace binding, actor
policy, live authority/catalog, process feature flags, and provider health. It
separately reports filesystem read/write, shell, CLI, MCP, skill catalog,
attachment modalities, app references, confirmations, recovery,
provider/upstream/data policy, certificate/suite/expiry, and TCB posture. The
same snapshot is projected without credentials to API, Chat, and Settings and
is recomputed before admission, continuation, request construction, catalog
materialization, confirmation resume, and dispatch.

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
independent server-owned availability and attestation boundary;
`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` remains false for this decision state.
Disabling egress enforcement blocks hosted export rather than
bypassing evaluation. Enabling the parallel-tool-call switch does not override
the MVP's sequential policy ceilings: codecs account for every call and the
shared loop durably denies/pairs all calls in a parallel response. The switch
only reserves an independent rollout control for future parallel execution.

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
10. complete concurrency, recovery, leakage, sub-agent, and rollback hardening;
11. close the Phase-1 attestation/classification, certified-schema/TCB,
    descriptor-relative filesystem, and effective-capability gates without
    enabling a remote profile;
12. close the Phase-2 provider-step journal, preliminary ledger, staged-state
    pairing, effect ordering, and productive recovery gates without executing
    a provider probe or enabling a remote profile;
13. close the Phase-3 step/tool budget separation and terminal
    step/output/cost/deadline reserve, tool-less provider payload, empty-output
    rejection, and one-recovery gates without executing a live probe or
    enabling a remote profile.

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
  text retain their existing behavior. Phases 1 through 3 supply the
  server-owned attestation/certified boundary, deterministic recovery, and
  governed finalization, but reopening still
  requires complete live/behavioral certification, onboarding, leakage review,
  canary, and release gates—not a browser declaration or a flag alone.
