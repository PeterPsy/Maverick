# Installation address management

Installation address configuration is a headless Core domain, owned by
`core/installation`. Settings and Base Shell are clients of the same admin-only
HTTP, CLI and MCP operations. Each standalone installation owns its domain,
DNS credentials, certificates and provider registrations.

`inspect`, `plan`, `apply`, `verify`, `rollback` and `status` expose typed,
credential-free results. A plan records a generation, exact DNS mutations,
required public endpoints and external provider actions. Applying the same plan
is idempotent; stale plans and concurrent address changes are rejected.

Local installation infrastructure state lives in `.maverick/installation`,
outside workspaces. It contains the active configuration, immutable plans,
durable jobs and redacted diagnostics. Root-only backups and Certbot credential
projections remain private. Core Secrets owns credential values; consumers use
platform delivery to the fixed DNS-provider API and Certbot, never tool results.

An operator-managed host worker handles queued jobs and resumes them after
backend restarts. It validates DNS delegation, writes only installation-owned
records, issues the main and `*.sidecars.<hostname>` certificates, tests renewal,
prepares Nginx, verifies HTTPS against the intended server, and atomically commits
the canonical address. Existing valid certificates are adopted. CA retry dates
and DNS propagation are persisted waiting states, not busy retry loops.

Cloudflare is the first executable DNS adapter. It supports zone-scoped tokens,
discovers the zone ID, preserves unrelated records and exposes a prefilled token
creation link. Manual mode produces exact provider instructions and remains
explicitly blocked until a supported DNS connection is supplied; it does not
claim unattended wildcard renewal without an automation credential.

Google's Core-owned OAuth callback and enabled app contract public endpoints
are included in the plan. Changing a configured provider's callback requires
explicit registration confirmation before canonical activation. Missing initial
connections are reported separately from web readiness. App declarations describe
dependencies only; they do not grant anonymous access or relax route ownership.

The Settings Installation page and the authenticated Base Shell setup route
share the workflow: address, DNS connection, plan, progress, external actions
and verification. The top-level setup view remains available before isolated
app frames can load. Provider credentials are entered into Core Secrets through
the protected human UI, while agent operations accept references only.

Moving a server while retaining its hostname updates the installation's own DNS
records and preserves callback addresses. Changing the hostname stages the new
origin while retaining the old configuration until checks pass. Rollback restores
only installation-owned DNS/configuration changes and retains unrelated settings.

The worker service is production infrastructure authorized by installation
administration. Status and stop commands are documented with its deployment
template; it is not an agent-owned detached task.
