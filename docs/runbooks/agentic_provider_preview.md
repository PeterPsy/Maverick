# Agentic provider preview operations

Status date: 2026-08-26

Scope: operator runbook

Production status: **NO-GO; all remote agentic execution contained**

This runbook governs the Google Gemini and fixed-upstream OpenRouter agentic
profiles. A capability certificate proves one exact implementation and provider
combination. It is not approval for customer data, arbitrary workspace data, or
production exposure.

Certificate evidence must be produced and published through
`docs/runbooks/agentic_certification_evidence.md` before this activation
runbook begins. This runbook never manufactures or repairs a certificate.

## Phase-0 containment procedure

Do not run a live Google/OpenRouter probe, certification live step, provider
HTTP request, or containment apply while reviewing the implementation. Obtain a
redaction-safe real-store plan through the operator-only Core CLI:

```bash
maverick core cli run core.providers.agentic.containment.dry-run --operator --json
```

The report must state `implementation_ready`, `dry_run_verified`, and
`live_apply_pending_review`; review every binding/profile/certificate/session
identity, current revision/status, target status, target digest, count, and the
whole `plan_digest`. It must contain no credential binding id, secret, request
body, tool arguments/results, private envelope locator, or provider payload.
Review inventory ambiguity per ordered provider step across the complete event
archive: a durable final output or a ledger-backed proposal closes that step;
request-count-minus-invocation-count is not evidence, and a step with neither
persisted outcome remains ambiguous.

Only after independent review may the orchestrator apply that exact plan:

```bash
maverick core cli run core.providers.agentic.containment.apply \
  --operator \
  --confirmation phase-0-reviewed \
  --plan-digest <REVIEWED_PLAN_DIGEST> \
  --json
```

A containment apply is a partial saga, not a transaction, and the command is
neither idempotent nor safe to retry. A changed plan digest, provider-record CAS
conflict, session-lifecycle conflict, audit failure, or any other apply error
may leave earlier targets narrowed. Stop, inspect the structured failed audit
(`partial_apply`, per-kind applied counts, safe failure code and target digest),
then obtain a fresh dry-run and review before issuing any later apply. Never
reuse the reviewed digest or retry by dropping it. After a reported success,
the reviewed operation is still consumed: run a fresh dry-run for verification
and require zero
remaining enabled/default remote bindings, selectable remote profiles, eligible
current remote suite-v8 certificates, or ambiguous unquarantined sessions.
Codex state and hosted text selection must be unchanged. Preserve the audit
digest and counts. Until apply plus that verification completes, the Phase-0
operational exit gate remains open.

## Invariants

- Remote profiles are non-selectable NO-GO records. Current profile policy
  lists only Core-classified `public`; the egress evaluator always rejects the
  legacy `workspace_internal_fake` value, and browser/app declarations grant no
  remote agentic authority. The exact `fake-data preview` label remains visible
  as a warning and is not rewritten into a release claim.
- Every session pins definition revision, engine, adapter, model, protocol,
  endpoint/upstream, credential binding, certificate evidence, egress policy,
  and policy ceilings once. Existing bindings are never rewritten in place.
- Live certificate, credential, definition, workspace binding, execution mode,
  health, and egress state may only narrow authority.
- OpenRouter remains pinned to `deepseek/deepseek-v4-flash` through
  `deepinfra/fp8`, with fallback disabled, required parameters, denied data
  collection, required ZDR, and verified router metadata.
- Tool calls are sequential. OpenRouter later-indexed proposals are discarded
  and never executed; only the validated primary call can advance the loop.
  Mutating and destructive work requires persisted confirmation. Ambiguous
  side effects become `execution_unknown` and are not replayed automatically.
- Provider-private bytes and tool payloads remain encrypted Core state. Never
  copy them into tickets, logs, prompts, analytics, or ordinary exports.

## Future pre-activation gate (suspended until Phase 1+)

This section is retained as future work and must not be executed during Phase
0. Feature flags alone cannot reopen remote agentic admission.

An operator must verify all of the following before enabling a workspace
binding:

1. The profile definition and certificate endpoints show the intended immutable
   revision, active unexpired certificate, exact adapter artifact digest, model,
   protocol, and upstream set.
2. The current matrices in
   `docs/reference/google_agentic_certification_matrix.md` or
   `docs/reference/openrouter_agentic_certification_matrix.md` match the
   deployed code and dated provider catalog.
3. A provider credential is delivered by a Core credential binding. No raw key
   is present in a workspace record, environment file, request body, or log.
4. A revision-bound, server-verifiable attestation defined by the later phase
   proves the allowed data classification; no client declaration is accepted.
5. The workspace policy is at least as restrictive as the profile: read-only
   Core filesystem capability, bounded steps/tokens/cost, no shell or writes,
   and confirmation retained for mutating/destructive classes.
6. The fixture-only certification manifest passes on the deployed source. A
   future operator-run live diagnostic, if required by the later release gate,
   is invoked separately and never becomes a manifest step or a repository
   check. Fixture evidence alone is insufficient for promotion.
7. Open platform security blockers in `SECURITY.md` remain acknowledged. Do not
   relabel the profile `available` or production-ready as part of preview
   activation.

Use Settings as the normal control surface. Its agentic panel reads:

- `GET /api/providers/agentic/profile-definitions`
- `GET /api/providers/agentic/certificates`
- `GET /api/providers/agentic/workspace-bindings`

During Phase 0, `POST /api/providers/agentic/workspace-bindings` may disable a
remote binding but cannot enable one. No fake-data confirmation field exists.
Settings preserves the full preview label and shows provider, upstream, data
destination, effective egress/data policy, attestation unavailable, and
certificate state; it has no browser data-class checkbox. A revision conflict
requires a fresh read and operator review; never overwrite it blindly.

## Canary and observation

Start with one synthetic workspace and one actor. Create new sessions only;
never retrofit a running session. Exercise a read-only request, one denied
unauthorized-tool request, cancellation, and restart recovery.

For each canary, verify:

- `runtime.authority.evaluated` identifies the pinned binding and current policy
  revision set by digest, without bearer material;
- `runtime.egress.decision` exists before each exported block and contains only
  classification, decision metadata, and keyed digests;
- `provider.usage` stays within the workspace token and micro-USD ceiling;
- tool events show one sequential lifecycle and no unconfirmed side effect;
- public events, audit, logs, UI, and exports contain no credential, private
  continuation, reasoning detail, tool arguments/result body, or host path;
- no default workspace binding was created outside the approved canary.

Stop the canary on any `provider_upstream_not_certified`,
`provider_routing_not_certified`, `egress_policy_drift_unresolved`, repeated
`provider_unavailable`, private-state integrity/quota failure, unexplained cost
increase, missing audit record, or leakage signal.

## Failure and recovery

Provider definition-status, binding, certificate-status, and provider-state
conflicts are record revision CAS failures. Moving a runtime session to
`recovery_required` is instead a legal transition serialized through the
session lifecycle handoff; do not describe it as provider-record CAS. Public
APIs expose only allowlisted quarantine reasons, while arbitrary diagnostic
detail remains Core-owned. Runtime tokens belonging to a quarantined session
have no operational authority even if their token record has not yet expired.

Before provider acceptance, a new operator-initiated turn may be attempted only
after the outage or policy issue is understood. After acceptance, do not retry a
request automatically. Preserve the journaled request id and continuation state
and enter recovery; an ambiguous mutation remains `execution_unknown`.

For `provider_private_integrity_failed`, `provider_private_codec_mismatch`, or
`provider_private_state_unavailable`, stop the session and preserve encrypted
state for investigation. Do not discard history and continue with a partial
vendor conversation. For `provider_private_quota_exceeded` or
`provider_private_size_invalid`, stop the turn, inspect bounded metadata only,
and reduce the synthetic fixture or open a reviewed quota change. Never bypass
the quota or copy plaintext state elsewhere.

Certificate revocation, credential disablement, workspace binding disablement,
profile suspension, or egress revision drift must block the next authority
refresh, including refreshes before private-state persistence, tool execution,
and confirmation resume. A provider request already accepted cannot be made
secret again; cancel its transport and follow incident handling.

## Rollback

Rollback is a control-plane narrowing operation first and a code deployment
operation second:

1. Run and review the store-backed containment dry-run above.
2. Apply its exact digest once. Binding/profile/certificate status writes use
   record CAS; ambiguous-session quarantine uses the serialized lifecycle
   handoff. The plan is auditable but not atomic or safe to retry.
3. Cancel active remote transports. Preserve `execution_unknown` and
   `recovery_required`; do not replay or manufacture a committed outcome.
4. Confirm Settings reports no enabled/default affected binding and that new
   remote session creation fails closed.
5. Preserve redaction-safe audit, usage, egress decisions, request ids, binding
   digests, and certificate status. Preserve encrypted private/tool state under
   the normal retention policy until ambiguity is resolved.
6. Revert or redeploy code only after authority is narrowed. Startup may publish
   a new immutable revision, but must not reactivate a suspended old revision.
7. If local Codex is the approved fallback, select it only for newly created
   sessions. Never migrate a pinned remote session to another engine, model, or
   upstream.

Reactivation requires a new immutable profile/certificate revision whenever
adapter bytes, codec, transport, provider contract, routing, or evidence change.
Repeat the full pre-activation gate and canary; do not clear a revocation or
reuse its certificate identity.

## Provider onboarding checklist

A new hosted provider is incomplete until it has an exact protocol codec and
bounded transport; state and tool-pairing semantics; request-time credential
delivery; private-state codec; per-block egress classification; cost estimator;
strict model/API/endpoint/upstream routing; deterministic malformed-stream,
outage, cancellation, replay, leakage, prompt-injection, quota, corruption,
revocation, drift, and child-agent tests; a dated certification matrix; an
expiring immutable certificate; preview-only Settings controls; and an explicit
rollback rehearsal.

Any unsupported capability fails closed. No provider-specific implementation
may bypass the shared tool catalog, confirmation ledger, private-state service,
egress evaluator, authority refresh, usage events, or audit surfaces.
