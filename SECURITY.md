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
- residual XSS risk in trusted shell and isolated app frontends
- app backend and lifecycle hook sandboxing gaps
- recovery automation full-access risk
- per-resource privacy approval and current physical-device evidence for any private PWA cache rollout

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

The current PWA cache rollout is governed by
`docs/adr/0012-transparent-pwa-cache-and-network-resilience.md`; ADR-0011 is a
superseded historical checkpoint. M2R persists only verified standard-shell
assets and public branding in owned Cache API namespaces. M3-M5 add the shared
scoped IndexedDB/OPFS mechanics, lifecycle cleanup, RAM retry, isolated app
origins, and parent-mediated data/file brokers; their private rollout gates
remain disabled by default. M6 adds aggregate diagnostics, deterministic
workspace/user cohorts, automated budget/retry audit, and explicit XSS/data
remanence review in `docs/security/pwa_cache_m6_review.md`.
Credentials, secrets, signed or object URLs, Browser sessions, Speech audio,
temporary archives, and all agentic authority/control-plane state are
network-only and must never enter Cache API, IndexedDB, or OPFS. A private
candidate fails closed without exact policy revision, reviewed classification,
top-level-host-attested user/workspace/app identity, a resource schema
revision, bounded retention, read-time sanitizer, quota estimate, and a fresh
access lease. Failed durable cleanup remains pending and blocks persistent
cache access; RAM fallback cannot report it as success. Browser-side encryption
with a key available to the same JavaScript is not accepted as an XSS boundary.
An app frame's `allow-same-origin` applies to its authenticated per-app,
per-session isolated origin, not the shell origin. Exact-source/origin/scope
parent brokers are therefore mandatory and no same-platform-origin fallback is
allowed. A trusted shell XSS remains inside the browser-storage authority;
encryption available to the same JavaScript is not a substitute boundary. Any
private-cache rollout still requires its resource privacy approval and current
physical-device evidence.

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

App entrypoints may reach their own sidecar only through a separately declared
invocation-scoped broker capability. Core binds the hashed capability to the
workspace, local app, service, trusted backend/CLI/MCP/reference surface,
actor, exact pass-through routes, TTL of at most 30 seconds, request budget,
and body bounds, then revokes it when the entrypoint ends. The SDK receives no
sidecar port, technical token, relay authority, or sidecar filesystem path and
has no direct fallback. Reference access is read-only and browser authority
does not imply entrypoint authority. This closes that transport path; app
backend and lifecycle-hook sandboxing remain open production blockers.

Design Studio's OpenDesign 0.16.1 integration has a narrower product gate. A
current schema-4 release record must run the official materialized OCI daemon,
the independently signed static web overlay, real Chromium, isolated sidecar
origins, the Unix broker, Storage, scoped restart, workspace A/B isolation, and
exact route denial. Marked-fixture migration/rollback is an independent gate;
the aggregate requires the exact canonical UI scenario set, every rollback
preservation proof, and signed overlay provenance matching the current upstream,
lockfile, runtime compatibility, and web patch series. The committed schema-3
record predates that series binding and is historical rather than current release
certification. Evidence is checked for complete correlation and absence of prompt, cookie,
bearer, provider payload, environment, host path, and secret values. This does
not close the launch blockers above or authorize production data, credentials,
internet exposure, or migration of an existing workspace.
