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
backend restarts. It validates DNS delegation, issues the main and `*.sidecars.<hostname>`
certificates, tests renewal, prepares Nginx and proves the intended server before
changing public DNS. It then writes only installation-owned records, waits for
public propagation, and atomically commits the canonical address. CA waits and
wrong-target failures leave public traffic on the original server. Existing valid
certificates are adopted. CA retry dates and DNS propagation are persisted waiting
states, not busy retry loops.

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

## Operations and deployment

HTTP administration is under `/api/admin/installation`: GET the base path or
`/verify`; POST `/plan`, `/apply`, `/status`, `/confirm`, `/retry`, `/rollback`.
All require a human administrator session. CLI/MCP ids are
`core.installation.<operation>`; agents need full-access administrator context.
For example, inspect `core.installation.plan` for its current schema, then supply
`address`, `target_ip`, and `dns_secret_ref`. `apply` accepts a `plan_id`, returns
a durable `job_id` and is idempotent. `confirm` accepts only known `action_ids`.

On a Linux systemd/Nginx host, install the Certbot Cloudflare plugin
(`python3-certbot-dns-cloudflare`) and the system Python D-Bus package
(`python3-dbus`). From the repository root, run:

```sh
sudo /usr/bin/python3 scripts/deploy/install_installation_worker.py
```

The installer discovers `maverick-core.service`'s RootDirectory, so normal and
migrated/chroot hosts use the same deployment path. A custom Core unit may be
selected with `--core-unit`. It installs `maverick-installation.service` and
`maverick-installation.timer`; the worker runs one bounded tick every 30 seconds.
The API service account owns public job metadata; root owns private journals and
credential projections outside the repository. Status/stop on the host:

```sh
systemctl status maverick-installation.timer maverick-installation.service
journalctl -u maverick-installation.service
systemctl stop maverick-installation.timer
```

A deployment bootstrap installs this worker once, before asking users to enter
their address. Queued jobs survive backend restarts; a host-side completion step
restarts Core only after activation. Once the new manager owns an installation,
it disables the previous `maverick-wildcard-tls.timer`. Local expiry checks run
at most every six hours and renew within 30 days of expiry; provider/CA failures
remain visible in status. Staging renewal tests run once per certificate/job.
Existing valid certificate lineages are reused without forced production orders.

Fresh installations route administrator login to `/setup` when the public
hostname is missing or no healthy unmanaged web configuration has been verified. Setup can be reached through an existing HTTPS origin or
a localhost tunnel before public DNS/TLS is ready. Credentials require a secure
browser context. The same UI is available in Settings → Installation later.

Server moves run on the destination after restoring application data, control
plane records, and the Vault encryption key/keyring. Keep the source available
while DNS caches expire. The worker proves that the reviewed public IP reaches
this destination's job nonce before changing the canonical address. It does not
transfer data, register a new Google project, or alter the source host remotely.
Name/domain changes pause for exact external callback registrations. Web readiness
is separate from optional provider/account connection readiness.

The normal installer renders/enables the same worker and seeds its metadata
directory for the Core service user. The legacy wildcard-maintenance templates
are excluded from new install plans. Each activation stages installation-owned
Nginx virtual hosts, even when retaining the hostname, so destination servers
receive the correct local port and certificate paths. Older virtual hosts stay
available for selective rollback.

After canonical activation, GET/HEAD web document requests to a previous public
hostname on the same server redirect to the new address without caching the
redirect, preserving app routes. `/setup`, APIs, app frames and localhost access
remain direct. Installed/native clients with a saved server URL must use the new
address; the UI reports this after an address change. Source-server writes should
be drained during a server move to avoid divergence while DNS caches expire.

Managed Nginx files include an installation id and hostname digest. Staging a
second hostname creates a distinct file and preserves active virtual hosts,
including while waiting for provider registrations. Rollback removes/restores
only its target hostname’s file. The initial live preview’s single-file Nginx
backup was migrated to this format before publishing the feature.

The legacy TLS timer handoff journals its enabled/active state privately and
restores it if the first adoption is rolled back to an unmanaged configuration.
The operator installer assigns metadata ownership to the Core unit’s service
account rather than assuming the environment file owner is that account.

Public IP discovery refreshes after a host boot change and at most every six
hours. Fresh/unmanaged setup defaults to that detected IP, including when an old
`.env` was restored on a destination. Installation infrastructure metadata is
host-local and should not be copied as tenant data to a new server.
