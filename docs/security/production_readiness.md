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

## Agentic Multimodel Preview Gate

ADR-0010 approves the architecture and implementation sequence for hosted
agentic model providers. It does not close any launch blocker. Until a separate
production security gate is approved, remote agentic profiles must remain
disabled by default, explicitly marked preview, and blocked by the independent
Phase-0 admission barrier. Current profile policy lists only Core-classified
public content, while the legacy fake class is always denied. Capability
certificates attest only to one exact
engine/adapter/provider/model/protocol/upstream combination and evidence suite;
they are not a platform production-safety certificate.

Core now persists certificate evidence/certificates as immutable control-plane
records, keeps revocation in a CAS status record, verifies live adapter and
upstream identity before execution, and records only a redaction-safe effective
authority digest. This closes the certificate-object implementation slice; it
does not relax the remote containment gate or any platform launch blocker.

The runtime now also persists per-block fail-closed egress decisions before
export and keeps provider-private/tool payloads in restart-safe, integrity-bound
encrypted session storage with explicit codec and quota failures. Audit records
contain keyed digests but no content, and generic provider events cannot carry
thought signatures. The shared hosted loop now passes deterministic
fixture-provider coverage for streaming, bounded sequential tools, persisted
confirmation, cancellation, restart deduplication, terminal outages, mid-step
revocation, egress drift, prompt-injection containment, explicit private-state
quota/integrity failures, child-agent binding isolation, and conservative
recovery. The operator runbook documents canary, observation, incident
recovery, and control-plane-first rollback. These phase-9 controls do not close
the production gate: remote profiles remain disabled until provider-specific
live evidence, leakage review, production key management, and the platform
blockers above are completed.

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
