# Agentic provider preview operations

Status date: 2026-08-27

Scope: operator runbook

Production status: **NO-GO; all remote agentic execution contained**

This runbook governs the Google Gemini and fixed-upstream OpenRouter agentic
profiles. A capability certificate proves one exact implementation and provider
combination. It is not approval for customer data, arbitrary workspace data, or
production exposure.

Certificate evidence must be produced and published through
`docs/runbooks/agentic_certification_evidence.md` before this activation
runbook begins. This runbook never manufactures or repairs a certificate.

## Phase-0 containment record and rollback procedure

Material P0 containment completed before this P3 repository closure. Preserve
the following redaction-safe evidence together: source revision
`69d9e10fea641f805c1c52801b7fd60a027b02f9`, plan digest
`02484a30f9ea7254c5deebd69e5af4416a22d8aecc006d81b7b5d6aad9c4578d`,
audit saga `4a6ab3ee-8b55-40c4-9dd6-2eba17bd9bdc`, apply artifact SHA-256
`5cd77cf01ab3e4ed12ca0ab76d3774dadf0482bd892821fb8883ef3cb2ab6898`,
post-apply zero-target digest
`56253919e93461e67b62a068e6e8718638475d05173dfff97b2912dcbeed2e77`,
and post-apply artifact SHA-256
`c6daa0b542edc92ef09116b323b1b024d3d1f94ef53aa85344eb55ea4aad733c`.
This closes material containment only; it is not release, certification,
preview/canary, migration, or production evidence.

Do not run a live Google/OpenRouter probe, certification live step, provider
HTTP request, or another containment apply while reviewing P3. The following
commands remain the control-plane-first rollback procedure for a future
incident. Obtain a new redaction-safe real-store plan through the operator-only
Core CLI:

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
digest and counts. Never infer release readiness from a successful containment
operation.

## Invariants

- Remote profiles are disabled, non-selectable NO-GO records. Current profile
  policy lists only Core-classified `public`. The evaluator can consider
  `workspace_internal_fake` only when the exact resource/version has that
  Core-owned classification, an active workspace-matching attestation covers
  its scope, and the selected policy allows that class and destination; none of
  those conditions can be synthesized by a browser/app declaration. The exact
  `fake-data preview` label remains visible as a warning and is not rewritten
  into a release claim.
- Every session pins definition revision, engine, adapter, model, protocol,
  endpoint/upstream, credential binding, certificate evidence, egress policy,
  and policy ceilings once. Existing bindings are never rewritten in place.
- Live certificate, credential, definition, workspace binding, execution mode,
  health, and egress state may only narrow authority.
- OpenRouter remains pinned to `deepseek/deepseek-v4-flash` through
  `deepinfra/fp8`, with fallback disabled, required parameters, denied data
  collection, required ZDR, and verified router metadata.
- Tool execution is sequential. Google and OpenRouter preserve and journal
  every indexed proposal, including later OpenRouter indices and calls decoded
  before a terminal stream error. A multi-call response is denied and paired
  in full; no call is discarded or executed. Mutating and destructive work
  requires persisted confirmation. Ambiguous side effects become
  `execution_unknown` and are not replayed automatically.
- Provider-step and tool-call budgets are distinct and restart-safe. One final
  request plus at most one recovery retain full output/cost/deadline reserves.
  Once tools close, Google omits `tools` and OpenRouter sends `tools: []` with
  `tool_choice: none`; both carry the exact Core finalization instruction.
  Whitespace is not success, and an unexpected final call is journaled and
  `budget_denied` before the single recovery.
- Provider-private bytes and tool payloads remain encrypted Core state. Never
  copy them into tickets, logs, prompts, analytics, or ordinary exports.
- Workspace attestation is a separate actor-attributed, scoped, revocable CAS
  record. Resource classification and the final egress decision remain
  independent; declaration can only narrow. Browser fields, policy ids, and UI
  labels have no authority.
- The effective capability snapshot is the intersection of certificate,
  profile, workspace, actor, live catalog, feature flags, and health and is
  shared by admission, request/catalog construction, API, Chat, and Settings.
- Remote certificates bind the canonical code-owned execution TCB. Any drift or
  missing legacy TCB identity is ineligible before creation, continuation,
  authority refresh, or dispatch. Manifest v5 statically audits six maintained
  import closures, including package initializers and the
  `core/inter_agent/generalist_context.py` content-composition path; a reached
  local dependency outside the artifact set makes identity calculation fail.

## Future pre-activation gate (suspended pending certification and release review)

This section is retained as future work and must not be executed as part of P3.
`REMOTE_AGENTIC_ATTESTATION_AVAILABLE` remains false; feature flags alone
cannot reopen remote agentic admission.

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
4. The active revision-bound server attestation is actor-attributed, scoped,
   unrevoked, workspace-matching, and matched to exact Core resource
   classifications. `workspace_internal_fake` additionally requires that the
   selected policy allow that class and destination. Attestation may only narrow
   policy; no client declaration or policy id is accepted.
5. The workspace policy is at least as restrictive as the profile: read-only
   Core filesystem capability, bounded steps/tokens/cost, no shell or writes,
   and confirmation retained for mutating/destructive classes.
6. The complete certification manifest passes on the deployed source in the
   trust order: deterministic conformance, operator-only synthetic live probe,
   behavioral conformance validation, then certificate publication. Ordinary
   repository checks explicitly select the fixture step and never run the live
   step; fixture-only evidence is rejected for signing and promotion.
7. Open platform security blockers in `SECURITY.md` remain acknowledged. Do not
   relabel the profile `available` or production-ready as part of preview
   activation.

Use Settings as the normal control surface. Its agentic panel reads:

- `GET /api/providers/agentic/profile-definitions`
- `GET /api/providers/agentic/certificates`
- `GET /api/providers/agentic/workspace-bindings`

Attestation mutation is intentionally not a browser surface. Trusted operators
use only the Core commands
`core.providers.agentic.attestation.status`,
`core.providers.agentic.attestation.issue` (expected revision plus the exact
`fake-data-scope-reviewed` confirmation), and
`core.providers.agentic.attestation.revoke` (expected revision plus reason).
Every mutation records the authenticated actor and an append-only redaction-safe
audit fact. Do not issue an attestation merely to exercise P3 or to bypass the
false availability gate.

While containment is active, `POST /api/providers/agentic/workspace-bindings` may disable a
remote binding but cannot enable one. No fake-data confirmation field exists.
Settings preserves the full preview label and shows provider, upstream, data
destination, effective egress/data policy, the read-only attestation projection,
effective capability/TCB posture, and certificate state; it has no browser
data-class checkbox. A revision conflict
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
Session containment is attempted and reread first; journal CAS and encrypted
diagnostic writes are independent, bounded follow-ups. Never make quarantine
conditional on a private-payload, audit, projection, or diagnostic success.

Before provider acceptance, a new operator-initiated turn may be attempted only
after the outage or policy issue is understood. After acceptance, do not retry a
request automatically. Productive recovery runs at startup/worker loss,
pre-admission, pre-prepare, uncertain cancellation, execution failure, and the
explicit adapter operation. It reads the pinned engine/adapter/provider/API and
exact codec from each provider-step journal; never substitute a current default
or migrate an old codec. An ambiguous mutation remains `execution_unknown`.

For each affected step, inspect only redaction-safe journal metadata:

- request/response ids and acceptance/stream status;
- journal and base provider-state revisions/digests;
- ordered proposal/disposition/result counts and pairing/commit status;
- request-lineage digest plus final-outbox identity/digest/size/delivery status,
  never its text or private locator;
- request phase/control digest, max-output/input/cost reservation, durable tool
  charges/result-byte total, and bounded provider usage counters;
- public recovery reason and timestamps.

Do not resolve or copy staged provider bytes, tool arguments/results, or the
private recovery-detail locator into a ticket. Recovery may attach an orphan
request-scoped staged blob, repair a proposal WAL half, materialize a proven
pre-effect denial/result, finish pairing, promote exact staged state, commit, or
consume a pairing. An explicit provider `cancelled`, `budget_exceeded`, or
`incomplete` terminal may return to the prior commit only when no call or staged
state exists. If acceptance, pairing, codec, state revision, or effect outcome
is not provable, retain `recovery_required`; repeated restart must not change
the terminal revision or repeat an effect.

A ready pairing can continue only under its original active turn and exact
source journal/request/input lineage. Never move it to a new user turn. A
terminal turn must either finish certified same-turn recovery or quarantine the
pairing. A committed final-output outbox is drained with its stable event ids;
do not call the provider again, and quarantine if its identity or private
payload cannot be verified.

For `finalization` and `finalization_recovery`, verify that the recorded request
control has no tools and that only one recovery exists. Never manufacture a
third terminal attempt or manually pair a finalization call outside the normal
denial-result saga.

Do not manually clear `recovery_required`. Queue, continuation, prepare,
dispatch, and token paths deliberately reject the session. Settings and Chat
may show only `provider_acceptance_ambiguous`, `provider_pairing_ambiguous`,
`provider_state_ambiguous`, `tool_execution_ambiguous`, or the generic public
fallback; arbitrary detail remains encrypted and Core-owned.

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
adapter-pinned finalization output/cost/deadline reserves and certified
empty-tool wire behavior;
strict model/API/endpoint/upstream routing; deterministic malformed-stream,
outage, cancellation, replay, leakage, prompt-injection, quota, corruption,
revocation, drift, and child-agent tests; a dated certification matrix; an
expiring immutable certificate; preview-only Settings controls; and an explicit
rollback rehearsal.

Any unsupported capability fails closed. No provider-specific implementation
may bypass the shared tool catalog, confirmation ledger, private-state service,
egress evaluator, authority refresh, usage events, or audit surfaces.
