# P6 certification and release boundary

Status: evidence-boundary checkpoints implemented; complete certification and
remote release **NO-GO**. The exact-checkout deterministic rerun has unresolved
failures documented in `docs/development/agentic_p6_validation_2026-09-06.md`.

The normative plan is `storage/generated/piano-definitivo-parita-agentica-modelli-hosted-maverick.md`
in workspace `default`, revision read on 2026-09-06 (SHA-256
`482566795fa8ac3737c1a7c0c0413aaa62ff380bd19bc2fd724027a42ee715de`).
Its P5 review checkpoint is `617ed21c39e6111e2bb0c8d102bfa34709312227`.

P6 distinguishes repository conformance, live protocol evidence, natural
behavioral evidence, independent security review, certificate publication,
disposable full-workspace canary, and an explicit release decision. A passed
fixture or a subprocess exit code alone is not a release approval. Synthetic
protocol probes are not natural behavioral conformance.

Certification is per exact API profile (including model, provider config,
endpoint/routing, recipe, and adapter), or per native runtime/provider
connection. Native model slugs inherit their connection certificate; a model
diagnostic must not mint a new connection certificate. Existing Codex revision
14 and its artifact remain outside the remote candidate revision cycle.

## Checkpoints

1. **Candidate identities and deterministic corpus:** hosted adapter 36,
   recipe 23, Google profile 45, OpenRouter profile 44, suite 40, and canonical
   TCB manifest 30. The corpus includes P5 family/pinning/onboarding, native ACP
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

The general production blockers in `SECURITY.md` require a separate security
review. Until the relevant evidence and approvals actually exist,
`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` stays false and Gemini CLI and remote
API agents remain unavailable. Changing a flag is not certification.
