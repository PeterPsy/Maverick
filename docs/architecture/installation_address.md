# Installation address management

Installation address configuration is a headless Core domain, owned by
`core/installation`. Settings and Base Shell are clients of the same admin-only
HTTP, CLI and MCP operations. Each standalone installation owns its domain,
DNS credentials, certificates and provider registrations.

`inspect`, `plan`, `apply`, `verify`, `rollback` and `status` expose typed,
credential-free results. A plan records a generation, exact DNS mutations,
required public endpoints and external provider actions. Applying the same plan
is idempotent; stale plans and concurrent address changes are rejected.

Local installation infrastructure state lives in `.loopino/installation`,
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

The current destination's canonical real installation root is
`/root/projects/loopino`. An offline relocation stops all installation writers,
preserves tenant identities and encrypted envelopes, and rebases only declared
technical paths. `core.installation.relocation` changes AppStore source paths,
workspace binding data roots and explicit local-project roots through adapters;
it validates all candidate paths before writing. Paths must be absolute, without
traversal, and match complete root components. Reapplying the move is idempotent,
even when the new prefix contains the old prefix as text. Tenant text,
attachments, secret AAD, grants and membership identities are not path fields.
Native environment and Certbot renewal configuration require their own typed
updates; OS registrations remain exclusive symlinks to protected backing files.
See [the relocation checkpoint](../development/loopino_root_relocation_status.md)
for the actual destination, receipts and remaining acceptance gates.

HTTP administration is under `/api/admin/installation`: GET the base path or
`/verify`; POST `/plan`, `/apply`, `/status`, `/confirm`, `/retry`, `/rollback`.
All require a human administrator session. CLI/MCP ids are
`core.installation.<operation>`; agents need full-access administrator context.
For example, inspect `core.installation.plan` for its current schema, then supply
`address`, `target_ip`, and `dns_secret_ref`. `apply` accepts a `plan_id`, returns
a durable `job_id` and is idempotent. `confirm` accepts only known `action_ids`.

On a Linux systemd/Nginx host, install `.[installation]` into the protected
installation `.venv` for Certbot and its Cloudflare plugin. The host system Python
requires D-Bus (`python3-dbus`). From the repository root, run:

```sh
sudo /usr/bin/python3 scripts/deploy/install_installation_worker.py
```

The installer discovers `loopino-core.service`'s RootDirectory, so normal and
migrated/chroot hosts use the same deployment path. A custom Core unit may be
selected with `--core-unit`. It installs `loopino-installation.service` and
`loopino-installation.timer`; the worker runs one bounded tick every 30 seconds.
The API service account owns public job metadata; root owns private journals and
credential projections inside the ignored installation-owned TLS directory. Status/stop on the host:

```sh
systemctl status loopino-installation.timer loopino-installation.service
tail -n 50 installation/logs/systemd/installation-error.log
systemctl stop loopino-installation.timer
```

A deployment bootstrap installs this worker once, before asking users to enter
their address. Queued jobs survive backend restarts; a host-side completion step
restarts Core only after activation. Once the new manager owns an installation,
it disables the previous `loopino-wildcard-tls.timer`. Local expiry checks run
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

Loopino phase 1 keeps every new installation-owned file inside
`/root/projects/loopino`. Main and wildcard Certbot operations, including dry-run
renewal and the Core worker, pass the same explicit config/work/log directories
under `installation/tls/certbot`. Private DNS credential projections are limited
to `installation/tls/credentials` (0600 files, 0700 directory, no symlinks).
They cannot target source, tenant storage or another site's Certbot lineage.
Browser exact-origin and External Apps use their separate installation-local
`data/` TLS roots. The existing host's Giuntitrail Nginx defaults, TLS lineage,
renewal, Docker services and Centrino services are outside this change.

The installer and address worker share the public catalog ingress renderer.
Only the main hostname serves the exact `/catalog/api/apps` JSON with
revalidation and checksum-named `/catalog/artifacts/` bundles with immutable
caching. Other catalog paths return 404; directory browsing and proxying to an
upstream company's catalog are not enabled. Source templates are prepared in
tranche 1; no live Nginx configuration is applied before deployment review.
The hosted worker and CLI share `LOOPINO_SERVICE_ENV_FILE`, defaulting to the
installation's `.env.loopino`; address commits never write a second env file.
This shared worker/Core configuration is root-owned, Core-group-readable at
0640, beneath real root-owned parents without group/world writes. The service
account receives no write/rename authority. Root worker installation verifies
this boundary before activation; typed address commits/restoration preserve
ownership, mode and unrelated bytes. A service-owned environment is rejected,
not adopted as trusted root startup configuration. Fresh root provisioning
writes trusted settings before enabling either unit.

Fresh provisioning creates the designated `data/app-artifacts` store at 0750 for
the Core publisher only when absent. Existing artifact owners, immutable material
and generation markers are never re-owned recursively; resolution retains the
protected namespace/ancestor checks and sandbox mounts remain read-only. The
separate private `tmp/` directory belongs to Core for its local control sockets;
`runtime/` holds installation-local app service state such as Browser's Lab worker.
Neither operation transfers source or toolchain ownership to the service account.

Core owns the shared atomic configuration writer, verified Nginx master control
and DNS credential projection in `core/installation`. Deployment scripts import
these implementations as command entrypoints. Installed CLI/Core imports must
work without the repository `scripts` namespace on Python's import path; neither
operator `PYTHONPATH` nor a service-owned source directory supplies privileged code.

Explicit stdout/stderr files for Core, rescue, watchdog and privileged workers
live under `installation/logs/systemd`. Each owned main/sidecar vhost explicitly
selects access/error files under `installation/logs/nginx`, including worker
renders and HTTP-only ACME templates. Prepare these real root-owned parents
before activation; never chown them to Core. Existing Giuntitrail log directives
and host log policy remain unchanged. Systemd registration/status metadata is
OS-managed. Application-internal mutable logs remain in the separate `logs/`
tree. Recovery helpers back up only their selected configuration/env files in
exclusive private `installation/backups/wildcard` or `installation/backups/azure`
directories; global `/var/backups` is not a Loopino destination.

The source tests verify root ownership/mode, synthetic group read with non-root
write/unlink/rename denial, protected parent and symlink rejection, and typed
update preservation. Deployment must repeat this with the actual Core account
and test non-root Bubblewrap/AppArmor execution; source tests are not live proof.

Every installer, native address/TLS worker, browser-origin client and operator TLS
oneshot selects `scripts/deploy/loopino-certbot`, a protected source-owned
launcher for the isolated `.venv` distribution, never global PATH
or `/usr/bin/certbot`. Install `.[installation]` into the protected isolated venv
(Certbot and dns-cloudflare 5.8.0). Preflight verifies real root-owned executable
and ancestor paths without group/world writes, and lists the Cloudflare plugin
using the same rooted config/work/log arguments. Arbitrary browser-origin Certbot
command overrides are removed. Giuntitrail's global Certbot, plugins, lineage,
logs and renewal service remain independent. Plugin listing is prerequisite
evidence only; issuance/renewal still requires authorized deployment and the new
human-entered token.

Persistence adapter cutover also requires trusted host-operator authority. The
service-user HTTP/CLI apply returns `host_operator_required` before opening the
target or copying any collections. Dry-run/status remain available to authorized
admins. During explicitly authorized drained maintenance, a root operator may
use the official persistence CLI with the protected service environment, review
the plan, apply, and verify restart/adapter state. Cutover atomically preserves
root ownership and 0640 mode; cutover grants Core no direct environment write
authority and introduces no cutover-specific privilege bridge. This phase uses
JSON and performs no production migration.

Certbot 5.8.0/configargparse reads `/etc/letsencrypt/cli.ini` and the HOME/XDG
user CLI default before an explicit `--config`; storage-directory arguments do
not suppress these reads. The source-owned launcher enters a private mount
namespace (`unshare --mount --propagation private`), masks the host default with
an empty read-only installation directory, and masks the privileged user's
implicit default. It supplies only root-controlled
`installation/tls/certbot/cli.ini`, rejecting external CLI-config selectors.
The installed third-party distribution and host files remain untouched. Mount
namespace support is a fail-closed prerequisite; no host security policy is
relaxed. All issuance, renewal, plugin preflight, native job actions and offered
operator commands share this launcher and explicit in-root config/work/log paths.

Privileged processes use `installation/privileged-home` and protected XDG/cache/
tmp children, all root-owned with real protected ancestors. Systemd ExecStart
and ExecStartPost use explicit `env` assignments after EnvironmentFile processing
and Python `-I` before imports; the system interpreter retains D-Bus support.
Worker env reload restores this context before privileged work. Core's writable
`data/service-home` and empty provider homes stay separate. Tests use harmless
synthetic host/user defaults in a private outer namespace and actual plugin
discovery, and verify isolated system/venv Python startup excludes user site.

`managed_exact` runtime issuance is root-operator-only with this launcher. A
service-user Core fails before directory creation or an ACME subprocess with
`managed_exact_operator_required`; installer preflight reports the unsupported
service role/mode combination. Root operator exact-host issuance remains
available. No issuer-specific sudo bridge, same-origin fallback or unprotected
issuer is added.
The authorized `loopino.giuntitrail.com` deployment uses `external_wildcard` and
the trusted root installation worker, with the new human-entered DNS token.
Non-root managed_exact functional acceptance is not claimed.

## Default workspace host privilege requirement

Every self-hosted Linux installation enabling the `default` workspace in
full-access operator mode must provision its actual runtime account with
`NOPASSWD: ALL` sudo authority and verify `sudo -n id -u` returns 0 from real
agent sessions. This applies equally to fresh installs and destination servers.
The account name is not fixed; `ubuntu` and `loopino` are equivalent when granted
the same authority. Core/providers keep their named non-root service identity.
Privileged shell commands use `sudo -n`; direct file tools retain normal Linux
permissions and official Core surfaces retain their authorization checks.

The installation owner explicitly prepares the account-specific policy.
The current installer does not automatically provision or verify that grant.
Neither successful HTTP/DNS/TLS checks nor a full-access badge complete operator
workspace acceptance. A real sandbox must still refuse elevation, and
non-default workspaces stay sandbox-only. Follow the shared
[host privilege runbook](../deployment/default_workspace_host_access.md) for
protected policy registration, verification and revocation on each server.

## Operator host access for this installation

The 2026-10-15 operator decision aligns the destination with the source
installation's observed full-access runtime: a regular Linux service/runtime user
can request root execution through non-interactive sudo. The source runtime is
`ubuntu` with `NOPASSWD: ALL`; this destination uses the equivalent rule for
`loopino`. This is an explicit installation-owner grant, not an authority
created by the Chat badge or a workspace membership.
The rule belongs to the Linux account and is not toggled by individual chats.

Core and native providers continue to start as `loopino`. Administrative shell
operations use `sudo -n`; direct file operations retain normal Linux ownership
checks. The grant therefore covers host administration when explicitly invoked,
including services, containers, packages and protected files. It is not limited
to the Loopino project. Existing full-access processes see sudo policy changes
without restarting Core or recreating a conversation.

The root-owned 0440 rule is backed by
`installation/sudoers/loopino-runtime-admin` and registered only through its exact
`/etc/sudoers.d/loopino-runtime-admin` symlink. Validate the candidate and complete
sudoers policy with `visudo`; never overwrite unrelated rules or change the Core
service to UID 0 for this purpose. Removing that registration revokes the grant.

The installed policy is:

```sudoers
loopino ALL=(ALL) NOPASSWD: ALL
```

The account-specific rule stays in ignored installation state. On each server,
the installation owner must prepare and verify the equivalent grant for its
actual runtime account; the installer does not silently create it.

This operator grant does not change runtime-mode resolution or sandbox mounts.
Non-default workspaces remain sandbox-only. Verification must prove that the
outer sandbox keeps no-new-privileges enabled, hides host sudo policy and private
paths, and cannot use sudo to obtain host authority. Full-access remains an
operator/break-glass execution capability, as described in the Core architecture.
