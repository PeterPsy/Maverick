# Agentic multimodel runtime epic

Status date: 2026-08-26

Target: Phase-0 remote containment; remote agentic release is NO-GO

Normative source: Maverick Agentic Multimodel Runtime specification, revision
2.1 (2026-08-16), and ADR 0010.

This tasklist records implementation state without treating code presence as
certification evidence. A checked implementation item still requires its phase
gate and relevant tests. Remote providers remain candidate preview profiles
until the later attestation, recovery, certification, and operational gates are
reviewed. A legacy certificate or client declaration is not authorization.

## Phase 0 — containment status

- [x] Hosted, Google, and OpenRouter agentic switches default off; unknown
  hosted agentic identities fail closed while Codex and plain hosted text keep
  their prior paths.
- [x] New remote sessions fail before persistence, pinned remote sessions fail
  again before dispatch, and client/browser fake-data declarations cannot
  authorize either path.
- [x] Store-backed dry-run/apply containment plans binding disablement, profile
  suspension, suite-v8 certificate revocation/ineligibility, and ambiguous
  session quarantine; provider records use revision CAS and session quarantine
  uses the serialized lifecycle handoff. Apply is partial, non-idempotent, and
  not safe to retry: every error or conflict requires a new dry-run/review and
  emits structured partial-count audit rather than a success claim.
- [x] Remote inventory reads every archive page and correlates each ordered
  provider step with a persisted final output or one or more ledger-backed
  proposals. A step with neither outcome is ambiguous; four tool steps plus a
  final response are not treated as a proposal gap.
- [x] `session_status=recovery_required` persists, projects safely through APIs
  and Settings/Chat through an allowlisted public reason, removes operational
  authority from associated runtime tokens, and blocks further turn/queue
  admission without claiming a complete recovery engine.
- [x] Chat excludes contained profiles and synthesizes neither consent nor fake
  classification; Settings keeps contained records visible as NO-GO with
  the exact preview label, provider/upstream/data destination, egress/data
  policy, binding, profile, and certificate state. Neither browser sends a data
  classification control.
- [ ] Review the real-store dry-run plan, execute the digest-bound live apply,
  verify post-apply state, and record the audit result. Until then the
  operational status is `live_apply_pending_review`.

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

## Later parity and preview gates still open

- [ ] Run the complete Google fixture contract/E2E suite on the exact
  deployable commit and adapter bundle. Certification manifests remain
  `fixture_contract`-only; any later operator live diagnostic is a separate
  release gate and must never be started by repository checks.
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

This tasklist does not claim that current repository checks are green. Phase 0
is not operationally complete: the real-store dry-run, separately approved
apply, and post-apply verification remain open. Internal preview and production
readiness remain later, separate gates.
