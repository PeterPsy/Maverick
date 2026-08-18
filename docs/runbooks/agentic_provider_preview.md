# Agentic provider preview operations

Status date: 2026-08-17

Scope: operator runbook

Production status: **not approved; public and synthetic data only**

This runbook governs the Google Gemini and fixed-upstream OpenRouter agentic
profiles. A capability certificate proves one exact implementation and provider
combination. It is not approval for customer data, arbitrary workspace data, or
production exposure.

Certificate evidence must be produced and published through
`docs/runbooks/agentic_certification_evidence.md` before this activation
runbook begins. This runbook never manufactures or repairs a certificate.

## Invariants

- Remote profiles remain `preview`, unbound by default, and restricted to
  `public` and `workspace_internal_fake` data.
- Every session pins definition revision, engine, adapter, model, protocol,
  endpoint/upstream, credential binding, certificate evidence, egress policy,
  and policy ceilings once. Existing bindings are never rewritten in place.
- Live certificate, credential, definition, workspace binding, execution mode,
  health, and egress state may only narrow authority.
- OpenRouter remains pinned to `deepseek/deepseek-v4-flash` through
  `deepinfra/fp8`, with fallback disabled, required parameters, denied data
  collection, required ZDR, and verified router metadata.
- Tool calls are sequential. Mutating and destructive work requires persisted
  confirmation. Ambiguous side effects become `execution_unknown` and are not
  replayed automatically.
- Provider-private bytes and tool payloads remain encrypted Core state. Never
  copy them into tickets, logs, prompts, analytics, or ordinary exports.

## Pre-activation gate

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
4. The workspace contains only public or explicitly synthetic fixtures and the
   administrator explicitly confirms the fake-data-only restriction.
5. The workspace policy is at least as restrictive as the profile: read-only
   Core filesystem capability, bounded steps/tokens/cost, no shell or writes,
   and confirmation retained for mutating/destructive classes.
6. The operator-run live synthetic probe passes with the deployed credential.
   Store only its redaction-safe evidence digest. A packaged fixture certificate
   alone is insufficient for promotion.
7. Open platform security blockers in `SECURITY.md` remain acknowledged. Do not
   relabel the profile `available` or production-ready as part of preview
   activation.

Use Settings as the normal control surface. Its agentic panel reads:

- `GET /api/providers/agentic/profile-definitions`
- `GET /api/providers/agentic/certificates`
- `GET /api/providers/agentic/workspace-bindings`

Enabling or changing a binding goes through
`POST /api/providers/agentic/workspace-bindings` with the current expected
revision, restrictive policy patch, actor policy, credential binding id, and
`confirm_fake_data_only_workspace: true`. A revision conflict requires a fresh
read and operator review; never overwrite it blindly.

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

1. Disable the affected workspace binding with its current expected revision.
   This stops new sessions and live-narrows existing ones.
2. Revoke the exact capability certificate with status revision CAS when the
   artifact, evidence, provider behavior, routing, or privacy claim is in doubt.
3. Suspend the affected immutable profile revision. Do not mutate its model,
   routing constraint, certificate id, or policy ceiling.
4. Cancel active remote turns. Mark ambiguous tool executions for manual
   reconciliation; do not replay them.
5. Confirm Settings reports no enabled/default affected binding and that new
   remote session creation fails closed.
6. Preserve redaction-safe audit, usage, egress decisions, request ids, binding
   digests, and certificate status. Preserve encrypted private/tool state under
   the normal retention policy until ambiguity is resolved.
7. Revert or redeploy code only after authority is narrowed. Startup may publish
   a new immutable revision, but must not reactivate a suspended old revision.
8. If local Codex is the approved fallback, select it only for newly created
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
