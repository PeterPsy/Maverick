# Production Readiness

Maverick is not production-ready.

Do not run an internet-exposed Maverick deployment with real secrets, customer data, or privileged connected accounts until the documented security hardening work is closed.

## Launch Blockers

- production secret backend and external key-management integration
- CSRF protection for unsafe cookie-authenticated requests
- authenticated app event WebSocket
- runtime token authority binding, expiration, and revocation
- app frontend isolation
- app backend and lifecycle hook sandboxing
- restrictive control-plane store permissions
- recovery automation policy gates
- remote agentic-provider egress classification and leakage review
- hosted tool-orchestration confirmation/replay and runtime-authority review

## Experimental Use Only

Acceptable current uses:

- local development
- fake data demos
- architecture review
- app SDK development
- sandbox and runtime policy testing

Unacceptable current uses:

- public internet deployments
- production OAuth accounts
- real customer data
- shared untrusted multi-user deployments
- third-party app execution without review
- remote agentic model profiles with real workspace, personal, customer, or regulated data

## Agentic Multimodel Preview Gate

ADR-0010 approves the architecture and implementation sequence for hosted
agentic model providers. It does not close any launch blocker. Until a separate
production security gate is approved, remote agentic profiles must remain
disabled by default, explicitly marked preview, and blocked by the independent
server-owned availability/admission boundary. P0 material containment is
recorded in the agentic tasklist; P1 implements the security boundary, P2
implements journaled recovery, P3 implements governed finalization, and P4
implements the reviewed semantic/full-workspace/provider closure, but
`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` remains false and no remote binding,
profile, or certificate is enabled. Current profile policy lists only
Core-classified public content. The fake class is not a declaration shortcut:
it requires exact resource-derived classification, an active scoped
workspace-matching attestation, and an allowing policy. No current contained
profile permits it.
Capability certificates attest only to one exact
engine/adapter/provider/model/protocol/upstream/TCB combination and evidence
suite; they are not a platform production-safety certificate.

Core now persists certificate evidence/certificates as immutable control-plane
records, keeps revocation in a CAS status record, and binds them to the one
deterministic code-owned certified-execution TCB. Signing, verification,
publication, execution binding, and live status recompute/compare the same
digest; drift or a legacy missing identity fails closed. Effective authority is
one intersection of certificate, profile, workspace, actor, live catalog,
feature flags, and provider health and is reused by admission, dispatch, API,
Chat, and Settings. This closes the P1-P4 repository implementation slices; it does
not relax containment or any platform launch blocker.

Manifest v27 makes the known transitive boundary executable through six static
import contracts and adds the exact executable roots for every built-in app
CLI/MCP surface admitted as a hosted read. Package initializers, the generalist
input-context projection closure, continuation/recovery, app-entrypoint, audit,
usage, and audited app-local execution dependencies must all resolve to hashed
artifacts; a newly reached local module or app-code drift outside the manifest
prevents authority or TCB identity calculation.

Hosted adapter 33 and the Full Workspace result contract
`codex-baseline-v20` are bound by TCB manifest v27. Google revision 41 and
OpenRouter revision 40 atomically claim that contract and the `maverick_agent`
family because the executable result gate reports all 24 required behaviors:
16 real filesystem, shell/process, and CLI/MCP capability paths, one concrete
inter-agent workflow, and seven security probes. Their exact profile policies
retain the required `cli`, `mcp`, `app-interface`, and `core-capability`
surfaces, and a public-resolver fixture proves complete live authority. The gate
caches only the complete successful result; transient, empty, and partial probe
evidence remains fail-closed and retryable.
The gate includes a production-composed inter-agent CLI-create/MCP-wait workflow
whose operation-specific effects and safe public projections omit all message,
prompt, event, participant-output, final-answer, label, and cleanup content. Its
seven negative behaviors cover
sensitive raw/base64/chunked filesystem marker narrowing, revoke-then-rebuild
filesystem lineage, delayed tool-result egress after revocation,
post-preflight provider transport, revocation between two provider events,
revocation during a real overlay commit, and immutable workspace snapshots in
both shell and managed processes. The bounded descriptor-confined staging copy
omits every root or nested `.git` component and never exposes the live workspace
namespace. Concurrent post-spawn create and rename probes cover read-only and
mutation-overlay modes. The direct filesystem boundary continues to reject the
same metadata paths.
Tool records and provider-state generations
retain exact mutable-authority id/revision/digest lineage. After endpoint
preflight, Core refreshes complete certificate, binding, feature, actor, health,
policy, Full Workspace, classification, and credential authority before commit,
then runs the same guard in the task that opens and first advances the lazy
transport. At each boundary the prepared request's remote classes, exact catalog,
surface kinds, and filesystem/shell flags are checked against the policy read
after the authority refresh. Core also compares the prepared semantic
projection with the freshly policy-narrowed authority, so app references,
skills, and runtime-capability blocks cannot bypass a tool-less revalidation.
Tool-call or cumulative tool-result-byte exhaustion closes the catalog; a
last-mile tightening releases an uncommitted reservation and rebuilds
finalization without tools, while a later lazy-open race is denied before
egress. Every later provider-stream advance uses the cheap
mutable-authority/TCB metadata, classification, credential, policy, and deadline
fence. Runtime-public
issue/revoke state is accepted only after its
pending audit and classification CAS are terminalized coherently; a CAS loss is
never recorded as success. Raw filesystem bytes are scanned before base64 and
the complete-resource class is retained across chunks. Shell/process overlay
batches revalidate before and after materialization and roll back on drift.
Every built-in app CLI and MCP descriptor now carries a conservative static
effect class; mixed operation runners also carry an exact argument-discriminator
map whose missing, malformed, or unknown value resolves to `unclassified`.
Hosted reads require the exact platform source, descriptor bytes, and
executable-closure digest recorded in Core-owned audit revision
`2026-09-03-p4-builtin-effects-execution-v3` and the certified TCB;
Core recalculates them at dispatch before the effect boundary. Workspace-local,
external, or drifted metadata/code cannot self-authorize. Production-composed
Storage probes discover and execute real
read-only CLI/MCP operations. Website Studio preview construction and document
caching are mutating, and state snapshots prove every remaining declared read
leaves its SQLite database and files unchanged. Other mutating and destructive
app operations remain denied before effect unless Core can supply the certified
result guarantee.
The profile, certificate, execution binding, provider request, recipe, and
authority snapshot also bind `model_revision` and its policy. Google uses an
exact catalog revision and compares the live `version`; OpenRouter uses the
explicit `provider_alias` policy while retaining its exact endpoint/upstream
catalog checks. A policy or revision mismatch fails before execution.
Those definitions remain uncertified, unbound, contained previews; the local
claim is not live-provider evidence or launch authorization. The adapter places
all provider-bound context in semantic-envelope schema v1/compiler revision 10,
materializes scoped instructions through the confined filesystem, requires
commit-bound instruction digests for direct mutations, and uses rollback-safe
batch COW overlays for shell/process effects. Terminal process polling is
mutating/non-retry-safe. Content replacements preserve mode, ownership,
ACL/xattrs, and exact file atime/mtime. Every pre-image remains descriptor-pinned
and is checked against its complete metadata/xattr snapshot, so a later metadata
race causes full rollback without losing the concurrent change. Metadata-only
directory/root effects and hardlinks are rejected rather than committed with
altered semantics.

Direct replacement/edit/patch now clones the existing mode, ownership, and
ACL/xattrs before exchange and propagates exact pre-image taint to the
post-image for version-bound read-after-write. The authenticated same-session
mutation result preserves the exact binding across hosted orchestrator rebuilds;
move rebinds that taint to the destination. Failed writes remove empty parents
they created, and move validates the exact source before it can create
destination parents. Skill catalog and semantic materialization retain the
lexical selection identity and reject every symlink component.

Production bootstrap installs a Core-owned content classifier and atomic
turn-manifest writer for prompt, instruction, reference metadata, and each
governed-context source chunk; composer ids cannot select a class. Marker
detection can narrow exact bytes but marker absence remains `unclassified`
unless an operator-issued, CAS-revisioned runtime-public policy authorizes Core
to classify the exact identity/revision/digest. Admission revalidates the
server-owned policy digest and revocation state. Denied bytes stay private
behind a call-paired public error. Core-certified CLI/MCP result declarations
may supply explicit authority, while app declarations cannot. Mutating
shell/process output is classified from the exact private-overlay result before
commit and the overlay is discarded on denial. Composite attachment metadata
is classified separately and restrictively joined with the file observation.
Each workspace reference carries a server-observed identity/revision/digest and
required encoding that Core injects into every matching filesystem read,
including its first chunk; skills export exact
classified `SKILL.md` bytes, and every semantic class is bound to the exact
projected digest. The runtime journals distinct source/projection evidence.
Exact app-reference observations still resolve through revisioned workspace
classification records.

Large artifact projections hash their provider-visible bytes while retaining
the original taint. External cancellation and COW commit share one linearization
gate, and every synchronous CLI/MCP/Core worker belongs to requested hosted turn
quiescence. Adapter close, explicit session termination, and idle reap finalize
managed-process registries and durable records; termination keeps handles owned,
signals known leaders, and repeatedly sweeps post-SIGTERM descendants before
release. Complete-request pressure can trigger one forced history compaction
below the private-state-only threshold. These are repository safety invariants,
not certification or remote-release approval.

The runtime now also separates actor-attributed CAS workspace attestation,
exact resource classification, and per-block fail-closed egress decisions.
Canonical provenance/trust/data-class joins, certified Core-only schemas, and
descriptor-relative race-safe filesystem observations prevent client promotion,
silent schema omission, and path-race classification. Provider-private/tool
payloads remain in restart-safe integrity-bound encrypted session storage;
public state retains only redaction-safe source digests/classes/trust, effective
class, codec/request identity, and turn generation. The shared hosted loop
passes deterministic
fixture-provider coverage for streaming, complete provider-call accounting,
provider-step CAS/WAL parity, bounded sequential tools, persisted confirmation,
staged-state pairing, cancellation, crash/restart deduplication, terminal
outages, mid-step revocation, egress drift, prompt-injection containment,
explicit private-state quota/integrity failures, child-agent binding isolation,
productive lifecycle recovery, cross-turn pairing denial, terminal-limit
containment, containment-first fault injection, and private final-output outbox
replay with one provider request and one terminal event identity. Phase-3
fixtures additionally prove separate restart-safe step/tool accounting,
step/output/cost/deadline reserves, tool-less Google/OpenRouter final payloads,
complete-terminal-request cost coverage, staged request-specific preflight with
tool-less fallback, deadline-fenced slow handlers and result persistence,
persisted execution leases checked atomically by the terminal success CAS,
request-scoped OpenRouter finalization,
whitespace rejection, journaled `budget_denied` final calls, and no more than
one finalization recovery. Phase-4 fixtures add production-composed
classification/continuation, recipe/catalog identity, independent context
reserve, pairing-safe semantic compaction, bounded result artifacts,
UTF-8/base64 attachment references, request-scoped OpenRouter authority, and
exact live provider preflight before egress commit. The fixture suite also
proves attachment-only admission, composite-taint denial,
multi-file rollback after late instruction or metadata races,
unsupported-directory/hardlink rejection, read-modify-write timestamp fidelity,
production app-reference classification, and non-retry-safe terminal process
commit. They also cover production bootstrap input, safe result withholding,
exact artifact projection digests, late-effect cancellation, managed-process
close, and below-trigger full-request compaction. The operator
runbook documents canary,
observation, incident
recovery, and control-plane-first rollback. These controls do not close the
production gate: provider-specific live and behavioral evidence, onboarding,
leakage review, canary, production
key management, and the platform blockers above remain open.

## Design Studio OpenDesign Gate

Design Studio has completed its app-scoped OpenDesign 0.16.1 production-path
acceptance using the official pinned OCI artifact, OS-confined sidecars, real
Chromium, Storage, core/runtime streaming, restart, two-workspace isolation,
and migration/rollback on marked fixture copies. Its redaction-safe product
record and 24-criterion evidence map live under `apps/design-studio/service/`.

This is an integration gate, not a statement that Maverick is production-ready.
The launch blockers above still prohibit internet exposure, real secrets,
customer data, untrusted multi-user hosting, and real workspace migration.

## Secrets Status

Core Secrets and Vault provide the platform-owned management flow for sensitive values: apps store references and grants, Vault calls admin-gated Core Secrets APIs, app entrypoints receive grant-authorized values only as ephemeral input, and HTTP responses expose metadata or redacted leases rather than raw values. Secret value envelopes use AES-GCM with operator-supplied key material, a stored key id, and AAD over the value format, secret id, and key id. `MAVERICK_SECRET_STORE_PREVIOUS_KEYS` supports decrypt-only previous keys during rotation, and legacy `mvr3secret1` values are readable for migration. This is still not a production secret-management guarantee. A hosted deployment still needs externalized key management, explicit rotation operations, audited operational access to key files and bootstrap secret files, CSRF protection for unsafe cookie-authenticated calls, and broader sandboxing before real credentials are acceptable.
