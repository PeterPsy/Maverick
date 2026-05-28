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

## Secrets Status

Core Secrets and Vault provide the platform-owned management flow for sensitive values: apps store references and grants, Vault calls admin-gated Core Secrets APIs, app entrypoints receive grant-authorized values only as ephemeral input, and HTTP responses expose metadata or redacted leases rather than raw values. Secret value envelopes use AES-GCM with operator-supplied key material, a stored key id, and AAD over the value format, secret id, and key id. `MAVERICK_SECRET_STORE_PREVIOUS_KEYS` supports decrypt-only previous keys during rotation, and legacy `mvr3secret1` values are readable for migration. This is still not a production secret-management guarantee. A hosted deployment still needs externalized key management, explicit rotation operations, audited operational access to key files and bootstrap secret files, CSRF protection for unsafe cookie-authenticated calls, and broader sandboxing before real credentials are acceptable.
