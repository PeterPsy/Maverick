# Cloudflare DNS-01 for standalone Loopino installations

This is installation-owned infrastructure. Each installation uses its own DNS
account, Vault credential and certificate. No shared Loopino DNS or TLS service
is involved. Installation UI work is separate from this operational transition.

The main origin `loopino.example.com` needs its existing HTTPS certificate. App
frames and sidecars need `*.sidecars.loopino.example.com`; `*.example.com` cannot
cover these deeper hosts. The Cloudflare DNS wildcard may resolve multiple
levels, but that does not change TLS wildcard matching rules. Session-specific
`af-` and `sc-` origins and their isolation remain intact.

## Credential delivery

Create a Cloudflare API token with **Zone / DNS / Edit**, restricted to the
installation's DNS zone. Save it in Vault as an API key with alias
`cloudflare-dns-api-token`. The account's Global API Key is unnecessary.

`scripts/deploy/refresh_cloudflare_dns_credentials.py` is a root-only Core
installation consumer. It uses the configured control-store adapter and the
canonical Core Secrets platform-delivery resolver. It does not bootstrap the
backend or deliver the token through a workspace app grant. It only emits
metadata; dependency exception messages and tracebacks are withheld.

The consumer projects the token to `/projects/loopino/installation/tls/credentials/cloudflare.ini`
(root-owned, mode 0600, parent 0700), inside the ignored installation-owned TLS directory. Certbot receives
the path rather than the token in command arguments. A lineage pre-hook refreshes
the projection on renewal, so Vault rotation takes effect automatically. A
failed refresh removes the old projection: Certbot's behavior of continuing
after a failed pre-hook cannot reuse a revoked credential. No credentials belong
in source, status files, agent results or logs.

The same consumer supports `--inspect-zone <zone-id>` for read-only API checks.
It reports zone status, nameservers, record names/types/proxy flags and a digest
of DNS behavior. Comparing this digest before and after a DNS-01 test verifies
that the temporary challenge was cleaned up and existing records were preserved.
It does not change proxy flags, mail records, SPF, DKIM or DMARC.

## Issuance and activation

`scripts/deploy/maintain_browser_origin_wildcard.py` is the operator-managed
maintenance job. Its production Certbot order requests only the sidecar
wildcard and uses `--keep-until-expiring`. A failed order persists the CA's
retry deadline; later executions skip secret delivery and ACME calls until that
deadline. An exclusive lock prevents concurrent maintenance executions.

Before first activation, the job runs a renewal dry-run against Let's Encrypt
staging. After that passes, `activate_browser_origin_wildcard.py` verifies the
wildcard SAN, validity and key match, backs up the Nginx configuration and
installation environment, and applies `external_wildcard` routing. The
transition preserves unrelated settings and restores both files on failure.
An already active configuration is a no-op.

After activation, the maintenance job opens a fresh random `af-` origin with
the default public CA trust store and hostname verification enabled. It only
reports `active` after this live TLS handshake succeeds. The backend restart
intent is persisted before changing the configuration, so a failed verification
or interrupted transition can be recovered by a later successful execution.

`scripts/deploy/reload_nginx.py` discovers the single running Nginx master,
validates its actual `-c` configuration and signals the same PID/start time.
This supports migrated chroot installations where the systemd bus or Nginx PID
file may be unavailable inside the installation. A renewed certificate uses
this reload hook. A TLS mode change creates a restart marker; the host service
restarts the backend once and then removes it.

## Host scheduling

Render `scripts/deploy/systemd/loopino-wildcard-tls.service` and `.timer` with
the installation root, public hostname, ACME notification email, Nginx path,
first eligible UTC attempt and host-visible restart-marker path. The service
also checks renewal of the existing main-origin certificate. Existing renewal
jobs for other domains are preserved.

For a migrated installation, the host service needs its installation
`RootDirectory`, `MountAPIVFS=yes`, and `RootDirectoryStartOnly=yes`. The
`ExecStart` processes run inside the installation, while `ExecStartPost` uses
the host's systemd to restart `loopino-core.service`. Render the marker using
the host-visible installation root in this case.

Enable the host-owned timer. This production timer is deliberately independent
of agent turns; it is part of the requested unattended TLS maintenance.

- Status: `systemctl status loopino-wildcard-tls.timer loopino-wildcard-tls.service`.
- Stop: `systemctl disable --now loopino-wildcard-tls.timer`.
- Interrupt an in-progress maintenance run: `systemctl stop loopino-wildcard-tls.service`.
- Credential-free job status: `/projects/loopino/data/wildcard-maintenance/status.json`.
- Manual check: start `loopino-wildcard-tls.service`; it honors the persisted deadline.

The timer checks every fifteen minutes. Valid certificates are retained without
new orders. A rate-limit recovery does not mean a production certificate has
already been issued: operator reports must distinguish successful staging
validation, scheduled production issuance and verified live wildcard HTTPS.
