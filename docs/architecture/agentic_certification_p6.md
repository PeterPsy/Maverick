# P6 certification and release boundary

Status: **P6-D passed** on frozen commit `5a7ca45a` (635 Google / 644
OpenRouter tests, zero failures/errors/skips). P6-L/S/R and complete
certification/remote release remain **NO-GO**; see
`docs/development/agentic_p6_deterministic_closeout_2026-09-06.md`.
The earlier reviews and failing baselines remain in
`docs/development/agentic_p6_review_fixes_2026-09-06.md` and
`docs/development/agentic_p6_validation_2026-09-06.md`.

The subsequent aggregate-budget and admission/publication work is not covered
by that historical freeze. Suite 44 / TCB 34 requires new exact-source
verification before signing or release; the independent candidate delta is
documented in `docs/development/agentic_p6_runtime_publication_delta.md`.

The normative plan is `storage/generated/piano-definitivo-parita-agentica-modelli-hosted-maverick.md`
in workspace `default`, revision read on 2026-09-06 (SHA-256
`482566795fa8ac3737c1a7c0c0413aaa62ff380bd19bc2fd724027a42ee715de`).
Its authorized operational addendum (section 16), written through Storage with
that SHA fence on 2026-09-06, has SHA-256
`0c8796ded071189b315982cd17596f001e02062c550c3be3f57b203f920069e9`.
It separates P6-D/L/S/R checkpoints without dropping any release gate.
The subsequent operator budget/candidate-isolation addendum (section 17),
also guarded through Storage, has SHA-256
`7fae659a9d903d0f776fb7f87526b8eda348aaa753e01c5ff555999e44990471`.
It authorizes the bounded operational work, not a release or waiver of evidence.
Its P5 review checkpoint is `617ed21c39e6111e2bb0c8d102bfa34709312227`.

P6 distinguishes repository conformance, live protocol evidence, natural
behavioral evidence, independent security review, certificate publication,
disposable full-workspace canary, and an explicit release decision. A passed
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
Google's project tier must be confirmed operationally; a local `free_tier`
policy is not proof of the provider's billing configuration.

Every live protocol transport must open the same private operator-owned SQLite
ledger with its expected policy digest. It reserves before egress in a durable
transaction shared across workers and process restarts; failed, ambiguous and
cancelled requests are not refunded. Pacing waits occur before transport, not
as provider retries. Transport/stream failures halt that provider durably.
Only payload digests, run identifiers, ceilings and reservation amounts are
retained, never credentials or request bodies. The ledger must remain outside
tenant/source mounts. Its authority is local spend/quota authority, **not**
workspace attestation, natural evidence, signer trust or a release permit.

Independent review found that the session/profile/queue/dispatch chain dropped
authoritative workspace context. The isolated candidate now forwards the live
workspace store at those boundaries and at hosted full/cheap transport refresh;
an earlier snapshot cannot mask revocation. Neither this correction nor flipping
the hard availability flag is release approval. A laboratory run of the real hosted loop is not a
substitute for the full API-to-dispatch canary. The correct full-path fix also
changes shared queue/handoff files declared in Codex's artifact. Such a change
requires a separate candidate deployment and explicitly reviewed native
revision/cutover, not exclusions from artifact hashing or global callbacks to
smuggle authority. The current Codex 14 deployment must remain untouched until
its successor is actually verified and approved. Native Gemini CLI still needs
its own approved connection/artifact path, not an API model certificate.

The current suite additionally runs production-composed API creation, synchronous
submission, catalog/egress checks, codecs and the real hosted loop against an
in-memory HTTP peer, with direct network access forbidden. It found and fixes
the completion boundary's engine/model-provider id mismatch: a durable hosted
final is reconciled against the model provider resolved from its persisted pin,
while lifecycle events retain the engine id. Exact content, session, provider
and exit-code conflicts still fail closed; no duplicate final is appended.
Fabricated HTTP bytes and certification observations are offline regression
evidence, not P6-L, a laboratory permission, or release approval.

Suite 44 also closes the observed green-footer/background-error gap. The
collector checks the whole fixture stderr for uncaught thread, destructor and
async-task failures before accepting its final unittest receipt. Rejected output
is still retained; no live probe starts after that failed fixture gate. At
publication, Core reparses the retained fixture and live-probe output bytes and
requires exact agreement with the signed step receipts. A valid collector
signature cannot replace those observed receipts or independent natural review.

Certification is per exact API profile (including model, provider config,
endpoint/routing, recipe, and adapter), or per native runtime/provider
connection. Native model slugs inherit their connection certificate; a model
diagnostic must not mint a new connection certificate. The active Codex revision
14 is not modified or cut over by this work. The shared queue/handoff delta is
explicitly represented by candidate revision 15, with its own digest and review;
the old connection certificate is never transferred to those new bytes.

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

1. **Candidate identities and deterministic corpus:** hosted adapter 40,
   unchanged recipe 24, Google profile 49, OpenRouter profile 48, suite 44, and canonical
   TCB manifest 34. The corpus includes P5 family/pinning/onboarding, native ACP
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

The separate natural observation report covers all 14 plan scenarios at each
claimed effort, with source/projection/effect/trace digests, exact boolean
checks, profile-specific resource bounds and zero absolute failure counters.
It must follow the fixture/live collection on the same target, commit and TCB.
The report attachment stores canonical bytes before returning its reference.
Collection stores actual stdout/stderr bytes; signing reads the full natural
prompt/trace/source/projection/effect closure through digest verification.
Publication uses installation-owned public trust, not a worker-supplied key map,
and requires a second independently trusted reviewer signature over the exact
signed run and artifact manifest. Key or principal aliases cannot manufacture
independence. The trusted reviewer must still inspect the actual retained
traces; cryptography cannot prove that a review happened or execute natural
tasks. Fixture/protocol-only collections are unsigned and ineligible.

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

This extension is API-scoped: native certificates keep an empty API target.
An empty target is omitted from the evidence hash domain so existing Codex
evidence and connection attestations remain byte-identical; a nonempty target
is always hashed and cannot use the historical evidence-validation path.
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

The general production blockers in `SECURITY.md` require a separate security
review. Until the relevant evidence and approvals actually exist,
`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` and the separate native connection barrier
`NATIVE_AGENTIC_ATTESTATION_AVAILABLE` stay false. Gemini CLI has its own
default-off `MAVERICK_FEATURE_GEMINI_CLI_PREVIEW` gate; the `google` native
connection is not added to the API allowlist or authorized by Google API flags.
Changing a flag is not certification.
