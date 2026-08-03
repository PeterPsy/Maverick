# Security Policy

Maverick is experimental software. Do not expose it to the public internet or store production secrets in it until the documented hardening work is complete.

For a compact boundary overview, read `docs/security/threat_model.md`. For the current production-use limitations, read `docs/security/production_readiness.md`.

## Supported Versions

Only the current open-source branch is supported during the pre-release period. No stable release line exists yet.

## Reporting Vulnerabilities

Do not open a public issue for a vulnerability.

Use GitHub private vulnerability reporting for this repository when it is available. If the repository host does not expose that feature yet, contact the maintainers privately and do not publish exploit details until coordinated disclosure is complete.

Include:

- affected commit or version
- operating system and deployment mode
- whether the instance was local-only, behind a reverse proxy, or internet-exposed
- reproduction steps
- expected and observed behavior
- impact assessment
- logs or screenshots with secrets redacted

## Current Security Status

Maverick is not production-safe for sensitive data on an internet-connected host.

Known launch blockers currently include:

- plaintext local bootstrap secrets
- missing CSRF protection for cookie-authenticated unsafe requests
- runtime bearer token authority gaps
- unauthenticated app event WebSocket
- same-origin mounted app frontend isolation
- app backend and lifecycle hook sandboxing gaps
- recovery automation full-access risk

## Safe Testing Expectations

- Use fake data.
- Use local-only deployments.
- Do not connect privileged accounts or production OAuth credentials.
- Do not paste real customer, financial, medical, legal, or infrastructure secrets into agents.
- Redact tokens, cookies, API keys, local paths, and workspace data before sharing reports.

## Scope

In scope:

- workspace isolation bypasses
- runtime token forgery or privilege escalation
- app frontend or app backend isolation failures
- secret leakage through logs, events, exports, app data, or generated files
- unauthenticated state-changing APIs
- dangerous default deployment behavior

Out of scope for the experimental pre-release:

- reports that require already having local administrator access to the same machine
- denial-of-service issues without a security boundary impact
- findings against private deployments not running public Maverick code
- social engineering against maintainers

## Security Posture

Maverick's intended security model is stricter than a personal-assistant trust model:

- non-default workspaces must be sandbox-first
- workspace roots are tenant boundaries
- app-owned data must stay under `workspaces/<workspace_id>/data/<app_id>/`
- app source and runtime agent processes should be treated as untrusted unless explicitly promoted to a trusted profile
- platform control-plane state and secrets are not app-owned data

This model is still being hardened. Public documentation must not claim production readiness until the audit blockers are closed.

App-owned HTTP sidecars that declare sandbox compatibility use the generic
fail-closed process boundary documented in
`docs/architecture/app_sidecar_execution.md`: an allowlisted environment,
bubblewrap filesystem/network namespaces, no egress, and an authenticated Unix
relay rather than a host TCP listener. This closes that specific sidecar launch
boundary; it does not close the unrelated application-backend, browser-origin,
CSRF, runtime-authority, or recovery blockers listed above.

Sidecars that declare the generic isolated browser-origin capability are served
by a reserved ASGI host router, never by platform-route fallthrough. Core owns
one-shot hashed tickets, distinct host-only sessions, actor/workspace/app/
generation/process binding, expiry/rotation/revocation, unsafe-request Origin
and Fetch Metadata checks, response filtering, CSP, no-referrer/no-store
headers, and redaction-safe audit records. Maverick cookies and sidecar
technical tokens are not forwarded. This closes the browser-origin boundary
for the declared sidecar profile; it does not change Maverick's broader
pre-release status or the remaining blockers in
`docs/security/production_readiness.md`.

Sidecar route authorization is exact and deny-by-default. Contracts cannot
provide prefix matchers or regex; named parameters consume one segment and
unsafe authorized routes declare their method. Static subtree rules are limited
to safe reads outside `/api`. Core rejects encoded slash/backslash/dot
traversal, double encoding, ambiguous host paths, and non-canonical Unicode
before applying `blocked > handled_by_core > pass_through` precedence.
