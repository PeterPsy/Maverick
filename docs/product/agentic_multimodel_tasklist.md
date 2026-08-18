# Agentic multimodel runtime epic

Status date: 2026-08-18

Target: internal preview with synthetic data; not production approval

Normative source: Maverick Agentic Multimodel Runtime specification, revision
2.1 (2026-08-16), and ADR 0010.

This tasklist records implementation state without treating code presence as
certification evidence. A checked implementation item still requires its phase
gate and relevant tests. Remote providers remain candidate preview profiles
until an executed, signed suite and live synthetic probe produce a certificate.

## Completed implementation boundaries

- [x] ADR and threat model define profile/binding separation, immutable session
  pinning, provider-private state, certificates, tool control, and egress.
- [x] Profile definitions, workspace bindings, immutable execution bindings,
  prepared-session barrier, provider-state CAS, and legacy session migration.
- [x] Async provider-neutral adapter contract and optional local lifecycle.
- [x] Certificate/evidence domain, signed certification runner, expiry,
  revocation, and live restrictive authority intersection.
- [x] Existing CLI/MCP/app-interface resolution reused for tool orchestration;
  persistent invocation, confirmation, and replay controls.
- [x] Bounded encrypted provider-private state and fail-closed per-block egress.
- [x] Deterministic hosted loop, sequential tools, budgets, streaming,
  cancellation, and recovery coverage.
- [x] Google and fixed-upstream OpenRouter codecs/transports plus candidate
  preview definitions and dated matrices.
- [x] Settings and Chat governance/selection surfaces.
- [x] Independent kill switches for the normative rollout boundaries.
- [x] Canonical architecture, security, reference, app README, provider runbook,
  and certification-evidence documentation mapped.

## Preview gates still open

- [ ] Run the complete Google contract/E2E suite and operator-only live
  synthetic probe on the exact deployable commit and adapter bundle.
- [ ] Persist its immutable evidence in the platform-owned store, sign the run
  with a trusted CI key, publish a Google preview certificate, and complete the
  one-workspace canary.
- [ ] Repeat the full independent evidence, signing, publication, catalog/ZDR
  reconfirmation, and canary flow before enabling OpenRouter.
- [ ] Record the focused agentic, fast, and applicable pre-merge suite results
  for the candidate commit; no certificate may substitute for these gates.
- [ ] Rehearse certificate/binding/provider kill switches, cancellation,
  ambiguous-side-effect recovery, and rollback with retained audit evidence.
- [ ] Close production blockers in `SECURITY.md` and
  `docs/security/production_readiness.md` under a separate security review and
  release decision. Preview completion must not check this item implicitly.

## Evidence and acceptance links

- Architecture decision: `docs/adr/0010-agentic-multimodel-runtime.md`
- Runtime/provider contract: `docs/reference/runtime_provider_model.md`
- Certification procedure: `docs/runbooks/agentic_certification_evidence.md`
- Preview activation and rollback: `docs/runbooks/agentic_provider_preview.md`
- Provider matrices: `docs/reference/google_agentic_certification_matrix.md`
  and `docs/reference/openrouter_agentic_certification_matrix.md`
- Security posture: `docs/security/threat_model.md` and
  `docs/security/production_readiness.md`

The epic is complete for internal preview only when every preview gate above is
checked with immutable evidence. Production readiness remains a separate gate.
