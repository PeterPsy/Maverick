# Threat Model

Date: 2026-04-23; agentic journal/recovery amendment 2026-08-27

## Purpose

This document gives a compact threat model for Maverick as an experimental, self-hostable, workspace-isolated AI operating environment.

It is not a substitute for deeper internal security review notes.

Use this document to understand:

- what Maverick is trying to protect
- where the trust boundaries are
- which attackers are relevant
- what is intentionally not promised yet

## Security Position

Maverick is not production-ready.

The system is designed around stronger boundaries than a single-user personal assistant, especially for non-default workspaces, but the implementation still has open security hardening work.

Current intended position:

- `default` workspace may remain an explicitly unsafe full-access development workspace
- non-default workspaces are supposed to be sandbox-first and approval-gated
- app-owned data is not platform control-plane data
- runtime agents, app code, and generated content should be treated as untrusted by default

## Assets To Protect

Primary assets:

- user identities and authenticated sessions
- workspace membership and governance state
- app installation state and app enablement state
- workspace-owned app data under `workspaces/<workspace_id>/data/<app_id>/`
- runtime session state and turn history
- provider credentials and platform secrets
- local files outside the active workspace boundary
- app store trust and installed app artifacts

Secondary assets:

- logs and audit records
- generated files
- deployment configuration
- contributor trust in release artifacts and dependency metadata

## Trust Boundaries

### Browser user

The browser user is authenticated through the platform, but browser-origin trust is not enough authority for unsafe operations.

Unsafe requests, websocket channels, and mounted app surfaces must still be validated by core policy.

### Workspace user

A workspace user is trusted only for the workspace permissions granted by the control plane.

Workspace membership does not imply full host authority.

### App frontend

An app frontend is a mounted product surface, not a trusted control-plane authority.

App frontends may be buggy or malicious and should not be able to escalate through same-origin assumptions alone.

### App backend

An app backend is app-owned code executed under a platform contract.

It should not be treated as inherently trusted simply because the platform launches it.

### Runtime agent

A runtime agent is a powerful untrusted principal that can read context, call tools, and make planning decisions.

Prompt discipline is not an adequate security boundary.

### Provider subprocess

Provider subprocesses such as Codex are trusted only within the authority explicitly delegated by the core runtime and execution policy.

They are not generic host-level authorities.

### Platform core

The platform core is the policy and orchestration authority.

Compromise of the core is catastrophic, so the architecture should minimize paths to core compromise.

### Local host

The local host, filesystem, service manager, and operator account remain outside Maverick's internal policy model.

Local administrator compromise is considered out of scope for product-level isolation promises.

### External providers and remote services

OAuth providers, remote model providers, remote app catalogs, and external APIs are separate trust domains.

Data sent to them leaves the local trust boundary.

Remote model providers used by the hosted agentic runtime are never runtime
authorities. They receive only content blocks and tool schemas that pass the
Core egress and effective-authority checks. Provider continuation data remains
private Core runtime state and is not a browser, app, or workspace capability.

## Main Attacker Types

Relevant attackers:

- malicious workspace content author
- prompt-injection attacker through web pages, files, emails, tickets, or tool outputs
- compromised or malicious app author
- compromised or malicious app store artifact source
- low-privilege user attempting escalation
- browser-origin attacker exploiting weak session or websocket controls
- compromised provider or remote service
- operator mistake that exposes unsafe defaults to a public network

## Main Attack Paths

### Prompt injection leading to tool misuse

An agent reads hostile instructions and uses legitimate tools for unintended actions.

The hosted agentic runtime treats model output and tool output as untrusted.
Tool availability is derived from the immutable execution-binding ceiling
intersected with live workspace, actor, app-mount, invocation, execution, health,
and revocation policy. Every proposed call is persisted before validation or a
side effect. Mutating and destructive calls require a one-shot confirmation
grant when policy requires it, and a crash after the side-effect boundary
produces `execution_unknown` instead of automatic replay. Prompt instructions
cannot expand this authority.

Provider-visible schemas are not trusted merely because a registry discovers
them. Only explicitly public Core-owned schemas covered by the exact TCB may
egress. App-owned, dynamic CLI/MCP, omitted, or uncertified surfaces block the
request with an allowlisted structured reason instead of being silently hidden.

### Remote model content exfiltration

An injected prompt, malicious tool result, compromised app reference, or
misclassified attachment may attempt to send workspace content, credentials,
host metadata, or runtime bearer authority to a remote model provider.

Every outbound content block receives a fail-closed Core `EgressDecision` bound
to destination provider/upstream, data class, provenance, trust level, and an
immutable policy revision. Unknown values are denied. Current contained
profiles list only content that Core classifies as public, and the legacy
fake-data class is always denied; secrets, credentials, bearer tokens, host
operational metadata, and unclassified content are always denied. Audit records
contain domain-separated HMAC digests and reason metadata, never raw content.
Redaction is a secondary transform rather than the trust boundary.

Workspace declaration, exact resource classification, and the egress decision
are independent. The declaration is an actor-attributed, scoped, timestamped,
revocable CAS record; browser input, egress-policy ids, feature flags, UI labels,
`workspace_internal_fake`, and the legacy declaration field cannot create or
replace it. Even a valid fake-data attestation only narrows authority. Prompt,
skill, attachment, app-reference, filesystem/tool-result, and provider-private
sources retain distinct provenance/trust/classes, and a restrictive join keeps
missing or mismatched resource classification `unclassified`. Transient prompt,
agent-instruction, and governed-context content is likewise `unclassified`
unless a trusted server admission resolver returns a canonical record matching
the exact turn/source identity and digest. A Core-owned writer conservatively
classifies the exact bytes and atomically persists one immutable manifest on
the turn; sensitive-marker detection may narrow, but marker absence remains
`unclassified` and source ownership alone cannot select a class. Governed context joins every
captured control, summary, task/result, and artifact entry and stays untrusted.
Non-resource CLI, MCP, shell, and process output has no generic public-content
fallback: exact result bytes are classified, and a denied result is retained
privately while only a public call-paired error reaches the provider. Any
variable-result operation able to create workspace/app effects is denied before
execution unless its egress outcome can be guaranteed. App claims are ignored
without removing read-only discovery/use. Direct replace/edit/patch and move
propagate exact version-bound pre-image taint to their post-image. Authenticated
same-session mutation results bind the exact observation across orchestrator
rebuilds; creation has no public fallback.

Every semantic classification is bound to the digest of the exact projected
bytes. Composite attachment blocks classify client metadata independently from
the referenced resource and join both taints; a benign file cannot promote a
secret-bearing name or id. Skill projection uses the exact confined
`SKILL.md`, without catalog/`state.json` metadata inheriting that file's class.
A missing component or digest mismatch becomes `unclassified`, and an
attachment-only turn does not synthesize an unclassified empty prompt.
Request-time large-result projection hashes the exact artifact-reference bytes
seen by the provider while preserving original class and trust as separate
taint evidence.
Server-materialized app references additionally require a workspace
resource-classification record matching their stable app/entity identity and
exact payload digest. Production bootstrap wires that resolver explicitly;
admitted metadata cannot classify the underlying reference by itself.

Residual risk remains because content classification and prompt/tool-result
provenance are security-critical enforcement paths. Phase-1 repository tests
cover false-promotion and leakage-safe metadata, but remote agentic execution
stays disabled and independently contained until complete live/behavioral
certification, recovery, leakage review, canary, and the broader production
blockers are closed.

### Profile, certificate, or routing substitution

An attacker may try to substitute a profile revision, credential binding,
adapter artifact, provider model, protocol, endpoint, or router upstream after a
session is created. A provider may also silently route to an uncertified
upstream.

The runtime session embeds an immutable execution binding. Capability derives
from an unexpired, unrevoked certificate matching the exact adapter artifact,
provider, model, protocol, routing digest, and effective upstream. Workspace
defaults are not consulted after session creation. Live state may only narrow
the pinned ceiling. OpenRouter agentic requests use an explicit certified
upstream allowlist, no fallback, required parameters, denied data collection,
and policy-required ZDR; no eligible endpoint means no request.

The certificate also binds the one code-owned certified-execution TCB manifest
and digest. It covers every authority-changing Core path plus Chat/Settings
governance. Suite construction, artifact bundle, signature/publication,
execution binding, and live status derive from that same manifest; the
publisher recomputes it. Drift in runtime API, classifier, input composition,
ledger/store, lifecycle, codec/transport, or UI governance invalidates remote
authority before create, continuation, refresh, or dispatch. Legacy remote
certificates with no valid TCB identity fail closed. Manifest v9 prevents a
covered module from outsourcing authority or provider content to an unhashed
local dependency: six code-owned contracts statically walk the relevant import
closures and package initializers, including
`core/inter_agent/generalist_context.py`; any reached path outside the artifact
set fails identity calculation.

### Confirmation and side-effect replay

A browser retry, worker crash, stale resume, duplicated provider call id, or
malicious actor may try to execute a mutating tool twice or reuse another
confirmation.

Every decoded provider call first becomes a revisioned preliminary Core record,
before catalog, schema, policy, budget, or effect handling. The resolved handle
is nullable; the safe name, call/request identities, ordinal/index, private
argument locator/HMAC, policy revision, and authority digest remain durable.
Exact replay deduplicates and divergent reuse of a call id fails closed. Google
and OpenRouter retain later indexed calls and calls decoded before a subsequent
terminal stream error. Unsupported parallel responses are fully journaled and
then denied/paired; calls beyond the remaining tool budget receive an explicit
`budget_denied` disposition. A secondary malicious call cannot disappear from
audit or execute outside sequential policy.

One-shot grants bind actor, session, turn, invocation, tool handle, canonical
argument HMAC, policy revision, and expiry. The active-to-consumed transition
is atomic. Proposal persistence precedes the proposed event; the started event
precedes the persisted effect boundary; result persistence precedes the
completed/failed event. `executing` is persisted before the boundary, and
uncertain mutating/destructive outcomes become `execution_unknown` and are not
replayed. Browser state and model-supplied ids are not authoritative.

### Budget exhaustion or silent terminal turn

A provider may consume every exploration step, output token, cost unit, or
deadline; continue calling tools after Core closes the catalog; or return an
empty final so that a turn appears healthy without a usable answer.

Hosted adapters pin terminal resources for one final request and at most one
recovery. Provider requests and tool proposals use separate durable counters;
journal schema v3 restores request reservations, usage, tool charges, and
result bytes after restart. Proposal and accepted charge share one CAS; a
terminal request above its certified per-attempt cost allocation fails before
transport, and each allocation covers a complete request at the hosted input
ceiling, including retained context/provider state and admitted tool results.
Live policy only narrows. Required credentials and coarse eligibility are
checked before catalog projection; per-request egress decisions remain staged
until the real provider-specific estimator fits. An exploration candidate that
crosses the reserve is discarded before egress commit and replaced by a
tool-less finalization candidate. Synchronous read tools are deadline-fenced
before protected terminal time; timeout publishes a deterministic ledger result
without private-payload I/O. The `executing` record persists a unique lease id
and UTC expiry, and terminal success includes revision, lease, and future-time
predicates in one collection CAS (locked local atomic replacement or Mongo
server `$$NOW`). A worker paused after its final cooperative check therefore
cannot win after expiry even when timeout persistence is delayed. Ambiguous
non-read effects remain `execution_unknown`. Once a reserve
boundary is reached, Core sends an empty tool catalog with an exact trusted
final instruction. Google omits `tools`; OpenRouter sends `tools: []` with
`tool_choice: none` and never persists the request-scoped instruction into
later-turn history. Codec drift fails before transport.

Whitespace is durably rejected and staged state rolls back. An unexpected
finalization call remains a preliminary ledger proposal, receives a persisted
`budget_denied` result, and can trigger only one tool-less paired recovery. A
second call is denied without another request and leaves the session in
`recovery_required`. Every terminal failure is a structured runtime error with
non-zero completion; no unconsumed call is hidden on a running session.

### Provider-private state disclosure or corruption

Provider continuation state, thought signatures, exact function-call pairing,
or opaque protocol steps may contain sensitive information or be corrupted to
change future model behavior.

The Core stores that state as bounded authenticated-encryption envelopes behind
Core-issued opaque locators. AAD binds workspace, session, engine, adapter,
codec, and schema. Ordinary APIs, UI, logs, app hooks, exports, and analytics do
not receive the content. Digest, codec, or version mismatch fails into explicit
recovery rather than best-effort parsing. Ciphertext stored in a workspace
runtime partition is not itself a resolution capability.

Streamed provider state is staged under a deterministic private locator and is
not authoritative continuation state. A revisioned provider-step journal pins
acceptance, response identity, codec, ordered proposal/disposition/result
identities, pairing, and commit. Promotion occurs only after final-output proof
or reconstructible tool pairing. Startup/worker-loss, pre-admission,
pre-prepare, execution failure, and uncertain cancellation run the same pinned
recovery. Unprovable state, pairing, or acceptance is quarantined by session
status CAS with an allowlisted public cause and encrypted Core-private detail;
queue, continuation, dispatch, and bearer-token paths then deny the session.
Containment precedes diagnostic storage and independently retries session and
journal CAS, so a private-payload, audit, projection, or journal failure cannot
turn diagnostic availability into execution authority.

A malicious or stale new turn also cannot use old provider state to suppress
its input: continuation requires the original active turn, source journal and
request identities, private-state generation, and exact input-lineage digest.
Terminal failure either seals that same-turn pairing or quarantines it.

Final text is encrypted in a deterministic private outbox before the journal
can commit. Stable output/completion delivery identities make crash replay
idempotent without another provider request. If the identity or payload cannot
be proven, recovery quarantines rather than asking the provider to regenerate.

### Orchestrator-authored authority escalation

An untrusted orchestrator may attempt to create a worker with invented system
prompt, skills, provider, grants, or a disabled agent type. Dynamic
orchestration therefore accepts only task objective, dependency, role, review
target, and an optional id from the compact server-authorized agent catalog.
The core resolves the selected definition and prompt through Chat's configured
dependency provider, validates the runtime skill catalog, and materializes an
immutable participant snapshot. Invalid selections fail closed; they never
fall back to model-supplied authority-bearing fields.

The same output also cannot claim reserved topology identities such as the
run's orchestrator participant id. Dynamic task materialization rejects those
ids before mutation and reuses a persisted participant only when its hidden
agent kind, child-runtime execution mode, task label, agent type, task-bound
snapshot digest, skill ids, and provider material all match. This keeps a model
output from turning the root orchestrator into its own delegated worker.

### Explicit skill path injection

A client may attempt to invoke an unknown, disabled, or out-of-allowlist skill,
or to replace a stable skill id with a filesystem path or symlink escape. Turn
requests therefore accept only `invoked_skill_ids`. Core resolves those ids
from the runtime session's selected enabled catalog, enforces the session
allowlist, and the Codex adapter reconstructs `SKILL.md` only below the
session-local `codex-home/skills` copy. Missing files, symlinks, non-files, and
resolved paths outside that root fail closed before provider dispatch. Runtime
hosted materialization also retains the lexical workspace catalog path and
rejects every symlink component before its descriptor-confined read. Runtime
paths are not included in public API or transcript event payloads. In
`explicit` mode Maverick also neutralizes Codex `$skill-id` mention syntax in
the provider-only text copy, while retaining the user's original text in the
turn and transcript. Structured, validated skill items are therefore the only
activation authority. An inter-agent participant snapshot is an allowlist, not
an invocation request: each automatic task or direct participant message must
carry its exact `invoked_skill_ids`, bounded to 32, and Core validates that set
against the immutable participant session before dispatch. An empty request
invokes no skill even when the participant allowlist or workspace catalog is
non-empty. Static executor modes persist the invocation receipt on the
participant task record, while HTTP, CLI, and MCP direct-send surfaces validate
and forward it per message. Dynamic planner prompts receive only server-owned
activation mode and allowlist metadata from a revision-verified materialized
agent catalog. The planner and task resolver use the same immutable snapshot;
Core retries a decision if compact, definition, or prompt revision changes
during materialization. Failed task causes are bounded before they are returned
in the control ledger.

### Participant output influencing the root generalist

The root generalist may receive a session-linked orchestration status read so
it can explain Agent nodes progress. That projection is read-only, bounded,
redacts common secret patterns, allowlists artifact reference fields, excludes
hidden participant runtime identifiers and raw tool payloads, and labels task
and result text as untrusted data rather than instructions. The original root
turn input remains the only user message persisted in the Chat transcript. The
provider-only attachment is applied in both synchronous and asynchronous
plain-hosted and agentic dispatch paths.

### Stale quality approval

An orchestrator may try to complete using an earlier approval after a later
review reports a critical issue. A completed negative or malformed reviewer or
security-reviewer verdict therefore requires completed material revision work
in its causal future before a later approval can pass; simply approving the
same unchanged output does not clear the veto. A failed reviewer task is also
fail-closed and remains unresolved until an approved retry or replacement
review depends causally on that failure. Every passing approval must still
cover the current material frontier. An orchestrator cannot hide a negative or
failed verdict in an unbound reviewer task: reviewer and security-reviewer
tasks without a `review_of` target and direct target dependency are rejected in
both live decisions and persisted replay. Recovery also validates the complete
persisted initial DAG before adding any task to scheduler state, preventing
unknown review targets or dependency cycles from entering execution through a
sequence of individually valid task records. Operational event flooding also
cannot evict persisted plans, task results, control application markers,
handoffs, or directives: those allowlisted recovery records are protected from
visibility-history retention and internal replay reads every page in causal
order before scheduling resumes. If an older or corrupted run already lacks a
terminal task result, recovery fails closed rather than risking duplicate task
side effects. User interruption does not create that gap: an active task is
synchronously closed with a protected `cancelled` result even before its child
session exists. A paused-run fence before and after child creation removes late
session records and files before they can receive work. HTTP, CLI, and MCP
resume share a cross-process run-control handoff with interrupt cleanup, then
wait for the previous scheduler owner; sidecars without that owner reject the
mutation. Cleanup can cancel only the recovery generation, runtime session, and
task captured when the pause won. Runtime worker activation is independently
compare-and-set under a cross-process session lifecycle handoff and rereads the
persisted turn and session, so a cancelled turn or stopped session cannot be
resurrected by an older worker snapshot. Provider start has a second bounded
handoff from the final persisted `active`/executable check through provider
acceptance for both plain-hosted and agentic sync/async paths; prewarm uses the
session-only equivalent. Late provider and provider-thread metadata writes are
partial allowlisted mutations under the same handoff, so they cannot restore a
stopped session from an older full record. Interrupt also publishes a durable
first-writer cancellation intent before waiting for provider acceptance.
Activation, provider start, and terminal reconciliation treat it as
authoritative, ordinary lifecycle saves cannot erase it, and stale terminal
writes are corrected idempotently. Plain-hosted request owners watch that
intent and persist request-finished acknowledgement after aborting the HTTP
response, so an interrupt issued by CLI or MCP in another process does not
leave provider work alive. The acknowledgement is fenced by owner kind, host,
process id, process-start token, and request generation. Startup and interrupt
polling close only an exact same-host lease whose process incarnation is proven
dead; identity mismatch alone never declares a live sidecar dead, while
unverifiable or foreign-host owners fail closed. App, HTTP, and inter-agent
callers retry provider interruption after the lifecycle handoff, and publish
cancellation evidence only when the authoritative transition actually returns
`cancelled`. Concurrent HTTP or app interrupts atomically claim one durable
cancellation intent, and only that claimant reports successful interruption.
Terminal-outbox ownership is independent and technical: a worker or another
caller may drain the single event, thread-release, and source-app callback
phases without creating a second public success.
The same fence covers the complete scheduler mutation path. Each scheduler
captures one recovery generation, and every run transition, recovery-ledger
write, task claim/finalization, and completion commit validates that generation
and an active run status under the workspace transition lock. Queued futures
cannot start after pause, late results cannot overwrite persisted cancellation,
and a stale control decision cannot move a paused run to completed. Pause and
participant snapshot are committed under that lock, preventing a newly claimed
task from escaping cancellation. Runtime turn queueing is guarded by the same
status-and-generation transition: if pause wins, no turn is persisted or sent;
if queueing wins, interrupt observes and cancels that turn and its hidden session.
Same-turn message admission uses the same runtime-session `turn_submit` authorization as ordinary turn queueing. It requires a workspace-scoped client message id, a currently active Maverick turn, a persisted provider-acceptance correlation, and an adapter capability declaration before provider input is sent. The client never supplies a provider thread or turn id. Steer-or-queue decisions are serialized per session and refuse to overtake already queued turns. Admission state is persisted before crossing the provider boundary; explicit rejection releases it for safe next-turn queueing, while transport uncertainty remains terminal so browser retries cannot duplicate an input that may already have reached the provider.

### Workspace escape

A non-default workspace runtime or app process reads or writes outside the workspace boundary.

Agentic Core filesystem operations pin the workspace-root descriptor and open
every component descriptor-relative with no-follow/directory flags where
available. They do not reopen verified paths, never descend automatically into
`.git`, bind chunks/list cursors to identity and version, and revalidate the
descriptor chain around use/commit. Repeated Linux tests swap final symlinks,
parents, directories, and the root during read/list/write and shell-cwd
admission; the fail-closed result must leave no outside read or write. Hosted
shell and managed-process writes are additionally isolated in a private overlay.
The live workspace is mounted read-only until Core validates the complete
bounded diff against every declared mutable scope and the actual root-to-target
instruction digest for each changed file. A nested-scope mismatch,
instruction-file or unsupported effect, non-zero exit, timeout, or interrupt
discards the overlay before it can affect workspace data. Effects cannot appear
later after a turn cancellation: the execution lease kills complete shell and
managed-process groups and waits for bounded workers to quiesce before returning.
Adapter-owned session cleanup also terminates managed processes, closes capture
descriptors, discards their overlays, and persists a terminal record before the
generic orphan scan. Newly-created
directories and hardlinked file effects are explicitly unsupported rather than
silently materialized with different semantics. Text creates/replacements
commit as one retained-preimage transaction; each descriptor-pinned pre-image
is checked against its complete metadata/xattr snapshot immediately before
exchange and against every preservable field afterward. A late content or
metadata race on any file rolls every earlier file back. File timestamps
accompanying content changes are applied exactly, while metadata-only
directory/root effects fail closed. Terminal `process.status` is a
mutating, non-retry-safe boundary because it performs that commit. The retained live-root
descriptor is consumed during mount setup and is not inherited by target code,
preventing a direct descriptor-relative write around the overlay. Broader
app/backend sandboxing remains a production blocker.

### Secret exposure

Secrets leak through files, logs, runtime state, generated files, or outbound actions.

Current mitigations require apps to persist only references or grant ids, keep raw values in AES-GCM Core Secrets envelopes, use action-scoped grants for app use, reject mixed-action wildcard target grants, require explicit targets for non-internal actions, validate structured HTTP/HTTPS targets or the `maverick://app.backend/*` platform delivery target family, strip query strings from audit targets, allowlist and bound audit request context, redact HTTP responses and audit payloads, fail closed with audit/event records when declared app-entrypoint grants are denied or missing, limit CLI/MCP delivery to command/tool descriptor `required_secrets`, ignore expired and non-deliverable grants during delivery selection, audit app-owned secret write create/rotate/grant operations, require admin authority for secret-mutating runtime CLI calls, and treat resolved values as ephemeral runtime input. Residual risk remains until the production secret backend, external key management, CSRF hardening, and app/runtime sandboxing blockers are closed.

Agentic model requests add a second mandatory boundary: credential resolution
occurs only at execution time, and neither raw credentials nor credential
bindings that could resolve them are serialized into prompts, public events,
provider-private envelopes, tool results, or egress audit content.

Each remotely exported agentic content block is classified by data class,
provenance, and trust and matched to the exact provider/upstream policy. Unknown
metadata and destinations fail closed. The `fake-data preview` text is retained
as a warning label, while current policy lists only Core-classified public data
and always denies the legacy fake class. Credentials, host metadata,
unclassified content, and
unmapped absolute host paths are denied. Persisted egress records use keyed,
domain-separated digests so low-entropy prompts cannot be recovered by hashing
guesses.

Opaque provider protocol bytes are encrypted with integrity-bound binding and
codec identities in a quota-bounded Core store. Their locators grant no read
authority. Ordinary provider events and state patches reject thought signatures
and raw private payloads, preventing accidental transcript, UI, app-hook, log,
or telemetry propagation.

### App privilege escalation

App frontend or backend code gains more authority than the app contract and workspace policy should allow.

For app-owned sidecars, browser and app-entrypoint authority are separate.
Entrypoints receive neither the sidecar port/technical token nor its private
persistence path. A core-owned Unix broker issues per-invocation capabilities
stored only by digest and bound to workspace, local app id, service, trusted
surface, actor, exact pass-through routes, TTL no greater than 30 seconds,
request budget, and body limits. Reference access is safe-read-only. Core strips
cookies and authorization, injects technical authentication only upstream,
audits issue/use/deny/revoke, and revokes at process completion. There is no
direct loopback or file fallback. Residual app-backend subprocess sandbox risk
remains a production blocker outside this transport boundary.

### Session and identity abuse

Cookies, bearer tokens, or websocket channels are reused to perform privileged operations.

Agent-facing historical transcript reads use the already lifecycle-validated
runtime bearer context but authorize the target separately. Same-workspace
membership and full-access execution are insufficient: only the target owner,
a workspace/platform admin, or a platform-minted `read_transcript` grant may
read it. Hidden inter-agent participant sessions and cross-workspace targets
fail closed as not found, and thread catalog filtering happens before search
and pagination so titles and counts do not leak. Transcript payloads are a
bounded allowlisted projection marked as untrusted conversation data. Opaque
snapshot cursors bind both event and turn eligibility to physical append
positions; timestamp ordering is applied only inside that immutable boundary.
Missing queued events may use pre-snapshot turn input only with an explicit
warning and incomplete projection, while mutable turn terminal state is ignored.
Structured keys are canonicalized across snake, kebab, and camel case before
sensitive-field filtering, and the projected structure has one global node and
serialized-byte budget with explicit truncation metadata. Read audits exclude
message content, prompts, tool output, paths, provider ids, and credentials.

### Supply-chain compromise

Dependencies, app artifacts, or release artifacts are replaced or tampered with.

## Security Goals

The near-term goals are:

- sandbox-first isolation for non-default workspaces
- explicit approval gates for destructive or externally visible actions
- no silent privilege expansion from app or agent code
- clear separation between control-plane state and app-owned data
- explicit disclosure that current local bootstrap and deployment are not production-safe
- immutable runtime execution binding with live authority that can only narrow
- per-content remote-provider egress decisions plus independent remote admission
- revisioned server-owned attestation separated from resource classification
  and egress, with a fail-closed provenance/trust/data-class join
- a single deterministic certified-execution TCB and certified public schemas
- descriptor-relative race-safe workspace filesystem primitives
- one effective-capability intersection shared by admission, runtime, API, Chat,
  and Settings
- persistent one-shot tool confirmation and no replay of uncertain side effects
- complete provider-call accounting, staged-state commit fencing, and
  lifecycle-invoked idempotent recovery with fail-closed quarantine

## Non-Goals For The First Public Release

The first public release does not promise:

- hardened production secret storage
- safe internet-exposed deployment
- robust same-origin frontend isolation
- zero-trust multi-tenant guarantees
- unattended full-access recovery automation on sensitive hosts
- production-grade app sandboxing for every backend and lifecycle hook path

## Reviewer Checklist

Before treating a change as security-relevant, ask:

- does it cross a trust boundary?
- does it increase app or agent authority?
- does it expose secrets or session state?
- does it broaden filesystem access beyond the workspace?
- does it introduce new network egress or write paths?
- does it weaken documented launch limitations?
