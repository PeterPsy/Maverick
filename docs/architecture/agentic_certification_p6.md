# P6 certification and release boundary

Status: the autonomous Candidate 49 execution reached the live boundary and
ended in the required **NO-GO** after the Antigravity live smoke failed; the
Google/OpenRouter live steps did not run on that halted job. The rollback
suspended API profiles 53/52, the remote flags remain off, no remote binding is
enabled, and no new certificate was published. Codex revision 15 remains
active and unchanged. See
`docs/development/agentic_p6_autonomous_execution_2026-09-09.md` for the
current operational record and
`docs/development/agentic_p6_deterministic_closeout_2026-09-06.md` for the
historical deterministic closeout.
The earlier reviews and failing baselines remain in
`docs/development/agentic_p6_review_fixes_2026-09-06.md` and
`docs/development/agentic_p6_validation_2026-09-06.md`.

That pass is historical. The current contained successor uses suite 50 / TCB
40 / hosted adapter 44 / recipe 25 / Google profile 54 / OpenRouter profile 53,
plus Antigravity native adapter/recipe 3 and Codex revision 15. It requires its
own exact-source operator record before signing or release. The source tree does
not treat a mocked probe receipt or this status paragraph as that record.

The normative plan is `storage/generated/piano-definitivo-parita-agentica-modelli-hosted-maverick.md`
in workspace `default`. Section 21 accepts one autonomous operator mandate
without waiving technical gates. Section 22 records the resulting automatic
NO-GO. The current Storage-owned revision has SHA-256
`8d2a029c85fd0270a9cda395806582b4e18a5a9525cf8510fa422afbe4215aa0`.
The plan revision read on 2026-09-06 had SHA-256
`482566795fa8ac3737c1a7c0c0413aaa62ff380bd19bc2fd724027a42ee715de`.
Its authorized operational addendum (section 16), written through Storage with
that SHA fence on 2026-09-06, has SHA-256
`0c8796ded071189b315982cd17596f001e02062c550c3be3f57b203f920069e9`.
It separates P6-D/L/S/R checkpoints without dropping any release gate.
The subsequent operator budget/candidate-isolation addendum (section 17),
also guarded through Storage, has SHA-256
`7fae659a9d903d0f776fb7f87526b8eda348aaa753e01c5ff555999e44990471`.
It authorizes the bounded operational work, not a release or waiver of evidence.
Section 18 replaces the prior native objective with Antigravity CLI and records
the operator's Google-tier approval. The official Storage surface returned
`authentication_required`, so the update used the documented direct fallback
only after verifying the section-17 SHA fence; the resulting document SHA-256
was `ad49b8ffc6c856b5d84393c327951af7ea393a5c1e6ec6fb9d95f99e251f08fa`.
After the final exact-source runs, the same concrete authentication failure
justified one SHA-fenced atomic fallback append of section 19. It records the
deterministic results and remaining NO-GO gates; the resulting document
SHA-256 is
`a27dc7553d5c8aa29739da1c12d51013b4595e2c3e6d6a069f06bcc567418999`.
After backend authentication recovered, section 20 was appended through the
official Storage MCP surface with that exact SHA fence. It records the
API-versus-OAuth correction and authenticated zero-generation Antigravity
catalog observation; the resulting document SHA-256 is
`ee71319648126704c089b10695a4426037c0201df1853cf77caf3b8df7dd1c86`.
Its P5 review checkpoint is `617ed21c39e6111e2bb0c8d102bfa34709312227`.

Section 21 was later appended through the official Storage surface and made
`VIA P6 AUTONOMO` the only remaining organizational input. It permits one
agent to collect, review after evidence, sign, canary and release, but only
when all existing technical gates are green. Section 22 records the actual
run against frozen commit `b5aa07dd1b83bf179ae8766c0f74293dfb087473`:
all three deterministic suites reached their live step, the live steps failed,
the successor ledger halted, and the downstream gates therefore did not run.
The private final record is
`/var/tmp/maverick/maverick-p6-autonomous-r48-68zsX93m/autonomous-execution-final.json`
with SHA-256
`24f38befc518f4097267eb3c8fd0d7f5665d37d64070e802aa182e203e4506d0`.
This is an operational NO-GO record, not certification evidence.

Section 23 records the contained Candidate-49 successor. Its exact-source
fixture suites passed with zero skips, but the Antigravity live smoke failed
after quota reservation, so API live collection and every downstream gate
were skipped and rollback was applied. The private final record is
`/var/tmp/maverick/maverick-p6-remediation-r49-indSclEi/autonomous-execution-final-r49.json`
with SHA-256
`b868ef9e1ea766bdc97c10b10a4cb640553d0dc50f2abc303f69497536b95979`.
This record grants no authority to Candidate 50.

P6 distinguishes repository conformance, live protocol evidence, natural
behavioral evidence, post-evidence security review, certificate publication,
disposable full-workspace canary, and an explicit release decision. Under the
section-21 mandate that review is autonomous and must never be described as
independent. A passed
fixture or a subprocess exit code alone is not a release approval. Synthetic
protocol probes are not natural behavioral conformance.

## Operator budget and remaining full-path work

The operator's updated authorization on 2026-09-06 supersedes the proposed
100 USD allowance: **OpenRouter at most 5 USD total; Google free tier only**.
The P6 worker defaults to a 4.50 USD non-refundable reservation ceiling, leaving
0.50 USD headroom, and 200 OpenRouter requests; Google has 80 generation
requests and at least 15 seconds between reservations. These are conservative
job limits, not claims about the remaining account balance or Google quota.
There is no automatic top-up, billing-tier change, quota reset, or paid fallback.
The operator confirmed on 2026-09-07 that the selected Google project tier is
approved. That confirmation satisfies the operator tier-approval input but is
not a provider billing receipt and permits no automatic paid fallback.

Every live protocol transport must open the same private operator-owned SQLite
ledger with its expected policy digest. It reserves before egress in a durable
transaction shared across workers and process restarts; failed, ambiguous and
cancelled requests are not refunded. Pacing waits occur before transport, not
as provider retries. Transport/stream failures halt that provider durably.
Only payload digests, run identifiers, ceilings and reservation amounts are
retained, never credentials or request bodies. The ledger must remain outside
tenant/source mounts. Its authority is local spend/quota authority, **not**
workspace attestation, natural evidence, signer trust or a release permit.

Independent review found that the prior session/profile/queue/dispatch chain
dropped authoritative workspace context. Candidate 42 closes that gap by
passing the explicit workspace store through profile pinning, session and child
creation, queue admission, provider handoff, authority refresh, continuation,
recovery, CLI/MCP and status paths. Every authoritative boundary re-reads the
typed persisted attestation; a persisted revocation overrides a stale supplied
snapshot and blocks before persistence, adapter/certificate work, or dispatch.
The hard attestation implementation is therefore available, but the independent
global and per-provider kill switches remain default-off. A laboratory run of
the real hosted loop is still not a substitute for the full API-to-dispatch
canary.

Candidate 43 additionally closes the direct-host operator attribution gap. The
`--operator` wrapper now derives a stable actor from the effective OS uid, while
a runtime-token supplied trusted context always wins and an agent cannot
self-elevate with that flag. TCB 33 covers the complete wrapper parsing,
context, descriptor and dispatch chain. Hosted adapter 39 also records the
post-r42 preflight source-byte revision instead of silently reusing adapter 38;
recipe 25 and the Codex artifact are unchanged.

Candidate 44 refreshes Google's authenticated stable-alias catalog identity.
The live `models/gemini-3.6-flash` record reports exact version
`3.6-flash-07-2026` and currently omits `baseModelId`. The preflight therefore
requires the exact resource name and version and rejects any supplied,
mismatching base-model id, while retaining the absent value in the
digest-bound snapshot. It does not weaken model pinning or permit a different
resource. The shared hosted adapter, TCB and both API profiles advance because
their source identity changes; recipe 25 and Codex candidate 15 remain
byte-identical.

Candidate 45 incorporates later source changes inside the broad certified TCB
and fixes a mismatch exposed by the first r44 Google live request. Google's v1
OpenAPI defines lifecycle interactions as partial resources, so their `model`
field may be absent even though the request and catalog target are exact. The
decoder now accepts omission on `interaction.created` and
`interaction.completed`, while still rejecting every supplied model mismatch.
The Google protocol codec advances to revision 4. The shared hosted adapter,
TCB and both API profiles advance; recipe 25 and the Codex candidate artifact
remain byte-identical.

Candidate 46 replaces the retired Gemini CLI objective with the installed,
content-pinned Antigravity CLI 1.1.27 runtime. Its documented persistent
`stream-json` protocol now has a supervised engine-owned launch path, exact
model pinning, private HOME/XDG roots, platform-resolved Gemini API-key
delivery, request-review soft denial, bounded/redacted tool-effect events,
resume identity fencing, and process-tree cleanup. The source changes advance
the shared TCB, hosted adapter, suite, and both API profile identities; hosted
provider wire contracts and recipe 25 do not change. Antigravity remains a
disabled Native candidate until its separate connection certificate, full
workspace evidence, trusted review/signature, and canary exist.

Candidate 47 corrects Antigravity's authentication boundary to match the
installed server runtime: the CLI uses its cached OAuth login, while Google AI
Studio and OpenRouter remain API providers with their separate Vault-backed API
keys. Core copies only an explicitly provisioned, private Antigravity OAuth
identity into each runtime, owns the sandbox settings, rejects API-key/provider
bindings on the native path, and discovers the live catalog through an
ephemeral confined copy of the same profile. Antigravity adapter/recipe advance
to revision 2. The broad shared TCB advances to 37, so suite 47, hosted adapter
43 and API profiles 52/51 bind the source change; hosted recipe 25 and Codex
revision 15 remain byte-identical. Catalog/auth readiness is not a connection
certificate or release approval.

Candidate 48 adds the missing independently certifiable Antigravity Native
connection path without manufacturing its evidence. The suite and behavior
schemas now support a `native_connection` target; a bounded live probe uses the
installed, content-pinned CLI and cached OAuth profile for one structured turn,
reserving Google free-tier quota in the shared durable ledger before egress.
Full Workspace execution gives Antigravity's native tools read-only workspace
access inside the outer Bubblewrap boundary. Selected workspace-owned skills
are copied into its private runtime home, while all mutations cross the
runtime-local `maverick` CLI/MCP boundary and therefore retain Core policy and
confirmation enforcement. A trusted signed suite-48 run may publish one root
connection certificate; current catalog slugs receive evidence-preserving
projections, and an operator must still explicitly activate the provider before
any separately governed workspace binding can exist. Removed catalog models are
unavailable; superseded projection revisions are suspended. The global and Antigravity-specific kill
switches remain default-off.

Candidate 48 also introduces an append-only successor-ledger operation for a
separately recorded operator authorization. It seals the halted predecessor,
carries all request and list-price exposure forward, and rejects expanded cost,
request, or pacing authority. It is not a reset/resume mechanism and no
successor has been created merely by adding the operation.

Candidate 49 hardens the collector discovered during the Candidate-48 live
attempt. Every fixture-contract subprocess now receives a disposable synthetic
environment rather than inherited production credentials, HOME, control-plane
paths, or live authorization. A failed, timed-out, or malformed step writes an
exclusive mode-0600 record outside the source tree containing output lengths
and hashes plus allowlisted reason/count fields, never raw subprocess output.
This collector change advances the suite to 49 and the broad TCB to manifest
39; hosted adapter 44, recipe 25, API profiles 53/52, Antigravity adapter/recipe
3, and the Codex revision-15 artifact remain unchanged.

Candidate 50 makes the Antigravity live boundary diagnosable without exposing
provider output or credentials. It preserves the primary prepare/execute
failure when cleanup also fails, maps only code-owned failures to bounded stage
reason codes, emits one redaction-safe JSON failure object, and treats an
incomplete close as a failed live observation. The suite advances to 50 and
the broad TCB to manifest 40. Because the Candidate-49 rollback suspended the
API definitions, Google/OpenRouter advance immutably to profiles 54/53 rather
than reactivating revisions 53/52. Hosted adapter 44, recipe 25, Antigravity
adapter/recipe 3, its pinned runtime artifact, and Codex revision 15 remain
byte-identical.

The shared queue/handoff fix changed files declared in Codex's artifact and was
published append-only as Codex revision 15, with revision 14 retained in
immutable history rather than hidden by exclusions or reused as a certificate
identity. Revision 15 is now the active verified Codex profile. This
Antigravity candidate does not change that artifact, restart or migrate the
Codex runtime, or reissue its certificate. Native Antigravity CLI still needs
its own approved connection/artifact path, not an API model certificate.

Certification is per exact API profile (including model, provider config,
endpoint/routing, recipe, and adapter), or per native runtime/provider
connection. Native model slugs inherit their connection certificate; a model
diagnostic must not mint a new connection certificate. Active Codex revision 15
remains outside the remote candidate revision cycle; revision 14 remains only
as immutable history and its identity is not inherited by revision 15.

### Recovery fixture scope

Generic continuation crash/fork/repair tests use an explicitly offline API
engine and independently issued, exact-target source/intermediate/target
certificates in a disposable store. Only the external release-containment
decision is stubbed; certificate validation, TCB checks, persisted governance,
compatibility proofs, process-absence fences and lineage writes remain real.
The fake engine cannot make provider calls. These tests are deterministic
state-machine evidence, not natural or live provider-continuation evidence.

The old fixture changed a Codex artifact but borrowed its current native
connection certificate. P5 correctly rejects that before considering generic
compatibility. Dedicated native regressions now assert this rejection, no
handoff/state transfer, and unchanged current Codex evidence. No native
validator or Codex artifact is relaxed to recover a green generic fixture.
Hosted provider-private/WAL recovery remains covered by its separate crash
matrix; an opaque native or hosted conversation is not assumed transferable
merely because a generic handoff fixture passes.

## Checkpoints

1. **Candidate identities and deterministic corpus:** hosted adapter 44,
   recipe 25, Google profile 54, OpenRouter profile 53, suite 50, canonical
   TCB manifest 40, Antigravity adapter/recipe 3, and active Codex revision 15.
   The corpus includes P5 family/pinning/onboarding, native Antigravity stream-json
   lifecycle, and hosted-text non-regressions, in addition to P0–P4.
2. **Evidence boundary:** exact-target, bounded, redaction-safe observed
   evidence must distinguish protocol smoke from the complete natural
   behavioral scenario set. Signing and publication must reject incomplete
   or mismatched evidence, including a green process with missing observations.
3. **Verification and operational handoff:** run the deterministic corpus on
   an isolated clean commit, preserve exact Codex identity and availability,
   and record missing live/signing/review/canary gates explicitly. No implicit
   release, control-store write, production workspace classification, or
   cross-family fallback is permitted.

## Evidence implementation

`certification_target.py` hashes every immutable API definition field except
publication time. The native target is separately connection-scoped and
requires a declared executable-artifact identity and Full Workspace contract; no
native model slug grants a new certificate.

The collector accepts only canonical manifest steps. Deterministic collection
requires the standard unittest success footer, a nonzero executed-test count and **zero
skips**; empty/partial green runs cannot silently close mandatory conformance.
Cold shell/process behavior checks use a unique session identity per invocation:
their real session-scoped orphan cleanup must not terminate another concurrent
check's worker, even when it runs in another backend/test process. Failed
observations remain fail-closed and uncached; isolation is not a retry policy.
Hosted shell/process launchers additionally establish their single terminal
session with `Popen(start_new_session=True)` before executing Bubblewrap. The
hosted command must not add a second `--new-session` inside Bubblewrap: that
would move descendants outside the group used by interruption, leaving an
early-startup termination race and an undrained output pipe. The process-group
regression checks a detached session, no controlling terminal, one shared
termination group and no surviving marked worker after interrupt. The native
Codex sandbox and generic process-control artifact are unchanged. This uses
the documented [Python pre-exec session boundary](https://docs.python.org/3/library/subprocess.html#subprocess.Popen)
instead of a second [Bubblewrap session boundary](https://github.com/containers/bubblewrap/blob/main/bwrap.xml),
not the removal of terminal isolation; all namespace, mount, network and
workspace-effect restrictions remain in place.
Hosted cancellation, output timeout and process interruption share a bounded
group-termination helper. After SIGTERM it always escalates the active owned
group to SIGKILL, even if the launcher has already exited during the grace
period: [namespace init can ignore SIGTERM before its handler is installed](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)
and keep the output pipe open. An already-reaped handle at entry never grants authority over a
potentially reused numeric group ID; session-owned orphan cleanup remains the
separate fallback. No generic/native process-control implementation is changed.
The live step additionally requires a strict, bounded receipt with the exact
target, fresh nonce, complete per-response protocol observations and exact
reasoning-effort counts. The
probes reject extra/unpaired calls, missing usage/state/completion, and empty
finals. OpenRouter's last-response failure cannot be converted into success by
aggregate counts. The probe transport requires explicit operator opt-in and a
bounded non-refundable cost reservation before the exact translated payload
reaches HTTPS; all responses retain the configured model/revision policy.
Stateful Interactions reservations include retained input/output ceilings, not
only the wire bytes of `previous_interaction_id`; ambiguous requests are never
refunded.

The Google collector runs the production OpenAPI/model preflight before **each**
of its three transport requests, including finalization. A missing/incompatible
catalog or a catalog change between rounds aborts before the next transport.
The receipt includes one verified catalog snapshot per request: observed API
and model revision, capability/limit metadata, endpoint-schema digest,
model-record digest and canonical snapshot digest. These snapshots are also
bound into the result summary. The validator checks exact identities, full
profile capacity, snapshot integrity/count and consistency across rounds; it
rejects the old catalog-free receipt even if its summary is rehashed. The
receipt's target is derived using the verified API/model observations.

OpenRouter preflight reads three official surfaces in one bounded parallel
window: `/api/v1/models`, the exact model endpoint catalog, and the ZDR endpoint
catalog. The main record must resolve to
`deepseek/deepseek-v4-flash-20260423`, be unexpired, and advertise exactly
`xhigh`/`high` with default `high` and `mandatory=false`. The DeepInfra FP8
endpoint must remain active, ZDR-listed, sufficiently large, and support every
parameter actually sent. Because its current catalog reports
`supports_tool_choice.none=false`, finalization omits both `tools` and
`tool_choice`; exploration alone sends a nonempty catalog with `auto`. The live
receipt binds the third-record digest and observed reasoning fields. With two
certified efforts, its bounded probe requires eight generations and six real
filesystem-list results.

The separate natural observation report covers all 14 plan scenarios at each
claimed effort, with source/projection/effect/trace digests, exact boolean
checks, profile-specific resource bounds and zero absolute failure counters.
It must follow the fixture/live collection on the same target, commit and TCB.
The trusted signer reviews actual retained traces; the report validator does
not execute natural tasks or turn user-supplied claims into trusted evidence.
Fixture/protocol-only collections are deliberately unsigned and ineligible.

The result summary and signed JSON bind the natural report; publication checks
the complete profile target again before creating a certificate. API certificate
schema 7 persists that target as `certification_target_digest` in both the
certificate and its digest-bound evidence. Status projection, admission, full
runtime validation and cheap authority refresh recheck it against the exact
stored profile revision. Runtime pins must also match the certified profile's
complete policy/context snapshots and configuration, not just revision labels.
A different API tuple cannot inherit a certificate; targetless API certificates
fail closed and are not backfilled. Workspace ceilings remain separately governed
and can narrow authority.

This extension now has two explicit scopes. API profiles bind their exact
immutable API target. A non-Codex Native candidate binds an exact
runtime/provider connection target including its installation, runtime artifact
and Full Workspace declaration; the model slug is deliberately excluded.
Historical exact Codex evidence keeps its legacy target shape and remains
byte-identical. A nonempty target is always hashed and cannot use the historical
evidence-validation path.
The source
TCB also includes the collection/signing entrypoint. This implementation does
not provide missing live credentials, trust a new signing key, approve native
runtime artifacts, run a canary, or close an independent security review.

The P6 integrity review also binds the app SDK display projector and the CRM
and Mail app-root display schemas to the TCB and executable app closures.
Backend imports load these schemas outside `backend/`; changing projected
fields must invalidate authority just like changing Python. Adding this
coverage does **not** refresh the existing built-in effect audit hashes: changed
app closures require their own effect/leakage review before reauthorization.
The subsequent scoped source review and regressions are recorded in
`docs/development/agentic_p6_effect_audit_2026-09-06.md`. Audit revision
`2026-09-06-p6-builtin-effects-reviewed-v4` renews only its ten reviewed
app/surface pairs, without classifying their content or granting egress.
Audit revision `2026-09-07-p6-builtin-effects-reviewed-v5` additionally renews
only the Design Studio CLI pair after review of the setgid operating-group lock
handoff added by `e5e6ec2e`. The handoff accepts only a regular, single-link
inode in the explicitly trusted operating group, fences the observed inode,
installs a new private `0600` inode atomically, and retains the existing lock
and race regressions. The scoped record is
`docs/development/agentic_p6_effect_audit_2026-09-07.md`. No descriptor or
effect classification changed.

The general production blockers in `SECURITY.md` require a separate security
review. `REMOTE_AGENTIC_ATTESTATION_AVAILABLE` is true because the persisted
server boundary is implemented; this is not a release switch. Until the live
and natural evidence, trusted signature/review, canary, rollback and production
approvals actually exist, the provider feature flags stay off and Antigravity CLI
and remote API agents remain unavailable. Changing a flag is not certification.
