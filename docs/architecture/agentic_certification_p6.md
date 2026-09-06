# P6 certification and release boundary

Status: implementation in progress; remote release **NO-GO**.

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

The collector accepts only canonical manifest steps. A live step additionally
requires a strict, bounded receipt with the exact target, fresh nonce, complete
per-response protocol observations and exact reasoning-effort counts. The
probes reject extra/unpaired calls, missing usage/state/completion, and empty
finals. OpenRouter's last-response failure cannot be converted into success by
aggregate counts. The probe transport requires explicit operator opt-in and a
bounded non-refundable cost reservation before the exact translated payload
reaches HTTPS; all responses retain the configured model/revision policy.

The separate natural observation report covers all 14 plan scenarios at each
claimed effort, with source/projection/effect/trace digests, exact boolean
checks, profile-specific resource bounds and zero absolute failure counters.
It must follow the fixture/live collection on the same target, commit and TCB.
The trusted signer reviews actual retained traces; the report validator does
not execute natural tasks or turn user-supplied claims into trusted evidence.
Fixture/protocol-only collections are deliberately unsigned and ineligible.

The result summary and signed JSON bind the natural report; publication checks
the complete profile target again before creating a certificate. The source
TCB also includes the collection/signing entrypoint. This implementation does
not provide missing live credentials, trust a new signing key, approve native
runtime artifacts, run a canary, or close an independent security review.

The general production blockers in `SECURITY.md` require a separate security
review. Until the relevant evidence and approvals actually exist,
`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` stays false and Gemini CLI and remote
API agents remain unavailable. Changing a flag is not certification.
