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

## Agentic Multi-Model Runtime Gate

ADR-0010 defines direct agentic profiles for native and hosted runtimes. Hosted
agentic activation remains an explicit administrator decision
and continues to require credentials, workspace policy, containment, sandbox,
egress, tool-effect, recovery and monitoring controls.

The OpenRouter GLM profile is published as `available` so a configured workspace
can use it. It is not silently enabled for every workspace and is never selected
without an active workspace binding. Google API activation is independent and is
not required for the OpenRouter path.

Core computes one effective authority intersection from the direct profile,
workspace binding, actor policy, credential availability, model/runtime health,
feature flags, execution mode, routing constraint, egress/data policy and live
tool authorization. This calculation is reused by admission, dispatch, API,
Chat and Settings. Mutable browser state cannot promote it.

Hosted requests retain these enforcement properties:

- provider credentials remain Core secrets;
- endpoint, model, upstream and fallback policy are pinned by the profile;
- all content receives provenance/classification and an egress decision;
- provider-private state remains encrypted and absent from public events;
- tool proposals are journaled before effect and deduplicated by provider call
  identity;
- mutating/destructive calls follow confirmation and effect policy;
- request, result, cost, output and deadline budgets are fail closed;
- cancellation, restart recovery and uncertain effects reach deterministic
  public states;
- authority is refreshed before network submission and every side effect.

Core-owned base tool schemas require the reviewed schema marker. Dynamic
CLI/MCP/app tools use discovery/invocation wrappers and are revalidated against
live app bindings, actor policy, effect declarations, executable closure and
result classification. This tool review boundary is separate from provider
admission and cannot enable a provider or model.

Runtime-public classification policy and workspace declarations remain
operator-owned, CAS-revisioned and revocable. App/client declarations never
classify data. Unknown or mismatched data stays unclassified and cannot egress to
a remote model unless current policy explicitly permits it.

Operational testing, leakage review, canary monitoring and rollback gates remain
required for production use. Test artifacts are evidence for reviewers, not
runtime authority. Failures must be repaired in the responsible profile,
adapter, provider config, credential or policy rather than masked by extending a
date.

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
