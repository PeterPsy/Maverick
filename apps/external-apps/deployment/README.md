# Public hosting on the installation domain

The rule is **`<app>.apps.<Maverick installation hostname>`**, on every machine.
Here it is `<app>.apps.maverick.loopino.ai`. `<app>` is the stable readable slug
plus opaque publication id, not a private workspace id. No sslip.io fallback,
new domain purchase, private same-origin path, or public Core route.

This is operator setup. Saving app settings does not provision infrastructure.
It never requires restarting Maverick Core or the chat.

## 1. Domain and DNS

Use the canonical Maverick installation hostname (the same value configured as
`MAVERICK_SIDECAR_INSTALLATION_DOMAIN`), without scheme, port, wildcard or path.
Do not infer it from a browser Host, forwarded header or app-frame origin.

The base `apps.<hostname>` and a fresh random `*.apps.<hostname>` must resolve to
this ingress; check all A/AAAA answers. Publish AAAA only if IPv6 reaches it.
Existing wildcard DNS may already cover these names, as on the current host.
Without matching DNS, setup is blocked: HTTP-01 cannot create DNS records.
Do not replace the user's domain to conceal missing DNS. Disable CDN response
caching: every request must revalidate public serving authority.

## 2. App and isolated listener

Install/enable the sealed platform External Apps source through Maverick, select
Website Studio for `static-exporter`, and configure **installation_domain** in
the authenticated app UI or its discovered official CLI. The public suffix is
always derived as `apps.<installation_domain>`. An existing nonempty catalog
blocks a domain change, rather than rewriting approved URLs. No site is published
by infrastructure setup; exact-plan human UI approval is still mandatory.

Render `supervisor.example.json` into `/etc/maverick/external-apps.json` with the
same installation hostname and only explicitly selected workspace/app ids.
Render `maverick-external-apps.service.example`, replacing:

| Token | Value |
| --- | --- |
| `INSTALL_ROOT` | Canonical Maverick checkout without symlink ancestors |
| `SERVICE_USER` | Trusted backend service account, not root |
| `SERVICE_GROUP` | Account group for app data and canonical JSON lock files |
| `INGRESS_GROUP` | nginx worker group, commonly `www-data` |
| `CONTROL_STORE_ROOT` | Absolute active canonical JSON store root |
| `APP_DATA_ROOT` | Exact `workspaces/<id>/data/<local_app_id>` path |

Confirm the active persistence adapter/path through official `core.persistence.status`
discovery. This unit is for the JSON adapter: only its three canonical read-lock
files and selected app data are writable. Do not grant a whole workspace/store.
For additional workspaces, add exact app-data `ReadWritePaths`. A Mongo deployment
needs a separately reviewed unit; never silently read a different store.
The child receives only read-only public mounts, no host network or private data.

Before replacing owned operator files, preserve a private backup and check no
other agent/operator is editing them. Validate and enable only this service:

```bash
systemd-analyze verify ./maverick-external-apps.service
sudo install -d -m 0755 /etc/maverick
sudo install -m 0644 ./external-apps.json /etc/maverick/external-apps.json
sudo install -m 0644 ./maverick-external-apps.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now maverick-external-apps.service
sudo -u www-data curl --unix-socket /run/maverick-external-apps-listener/public.sock \
  -sS -o /dev/null -w '%{http_code}\n' -H 'Host: invalid' http://localhost/
```

Expect 404. Confirm `/run/maverick-external-apps-state/mounts.json` has the intended
namespace and fresh expiry. A healthy socket with an empty mount list does not
prove workspace availability.

## 3. HTTP-01 and exact HTTPS hosts

Prerequisites: nginx with `ssl_reject_handshake`, Certbot, system Python with
`cryptography`, public port 80 for HTTP-01 and port 443 for HTTPS. No port 53, DNS
API token or wildcard certificate is needed. The root-owned timer issues exact
SAN certificates only for catalog-derived names, never arbitrary incoming SNI.

From this directory, render the dedicated ingress in a staging directory:

```bash
python3 -B -c 'from tls_config import render_ingress; print(render_ingress("maverick.example.com"))' > /tmp/external-apps-nginx.conf
```

Use the actual installation hostname. Keep the generated upstream, HTTP-01 root,
owned include path and Unix listener aligned. The namespace catch-all rejects
unknown TLS names instead of routing them to the private default host. The exact
base certificate serves only a runtime 404; it is not an application.

Review nginx's existing `http`-context hash policy: long exact publication names
need `server_names_hash_bucket_size 256`; the 64 × 100 cap is covered by
`server_names_hash_max_size 8192`. If neither directive already exists, install
`nginx-http.conf` as `/etc/nginx/conf.d/maverick-external-apps-hash.conf`. Otherwise
review the existing owner's values; do not add duplicate global directives.

Install root-owned operator material (not writable by the app/public child):

```bash
sudo install -d -m 0700 /var/lib/maverick/external-apps-tls
sudo install -d -m 0755 /var/lib/maverick/external-apps-acme
sudo install -d -m 0755 /usr/local/libexec/maverick-external-apps /etc/nginx/snippets
sudo install -m 0644 tls.py tls_config.py /usr/local/libexec/maverick-external-apps/
sudo install -m 0644 nginx-proxy.conf /etc/nginx/snippets/maverick-external-apps-proxy.conf
# First installation ONLY; never truncate an existing hosts.conf:
sudo test -e /var/lib/maverick/external-apps-tls/hosts.conf || \
  sudo install -m 0644 /dev/null /var/lib/maverick/external-apps-tls/hosts.conf
sudo install -m 0644 /tmp/external-apps-nginx.conf /etc/nginx/sites-available/maverick-external-apps.conf
# Create the matching sites-enabled symlink only if absent.
sudo nginx -t && sudo systemctl reload nginx
```

The ACME challenge path must now be reachable. Test staging HTTP-01 against the
same webroot, using separate temporary Certbot config/work/log directories; never
install an untrusted staging certificate in production nginx. Then install
`maverick-external-apps-tls.service` and `.timer` in `/etc/systemd/system/`, run
`systemd-analyze verify`, `systemctl daemon-reload`, and
`systemctl enable --now maverick-external-apps-tls.timer`. For initial provisioning,
`systemctl start maverick-external-apps-tls.service` runs one pass synchronously.

The worker uses its own `/var/lib/maverick/external-apps-tls/{config,work,logs}`;
existing `/etc/letsencrypt` lineages and `certbot.timer` are untouched. It checks
fresh supervisor intent and renews within 30 days of expiry, once per minute.
Certificates group up to 100 names per app namespace, plus a separate base lineage.
Four orders per pass, 2-minute success coalescing and 1-hour failure backoff limit
work. CA quotas can still delay issuance. Certbot diagnostics stay operator-only.
Prepared hostname metadata enters certificate transparency before publication;
no content becomes public until human-approved apply. TLS pending returns
`public_tls_not_ready` without consuming the plan or changing the binding.

The worker validates key matching, SAN scope and dates; only exact nginx hosts
are generated. It checks the complete live nginx configuration before every
reload, restores only its owned include on failure and retains a retry marker.
Never reload a configuration known to be invalid. Existing private hosts and
Core PID/start time must remain unchanged. Do not run the general installer.

## 4. Browser boundary and acceptance

Subdomains share a site, not an origin. Public static documents use CSP
`sandbox allow-scripts` without `allow-same-origin`: no cookies, browser storage,
document.domain, forms, frames, workers or network APIs. Public CORS `*` allows
anonymous modules, lazy chunks and fonts, never credentials. Ingress strips
Cookie/Authorization/Set-Cookie and has no private/error-page fallback.
This is a stateless static/SPA product; authenticated apps require a separate design.

Verify trusted HTTPS for the base and provisioned hosts without `-k`. Unknown
names must reject TLS (not request a certificate or show Maverick). Check HTTP-01,
GET/HEAD, ETag revalidation, private-route rejection, listener loss and Core health.
Complete the [publication acceptance gates](../README.md#deployment-acceptance)
with an explicitly approved synthetic static build and SPA from an external browser.
Local tests/base TLS are not proof of a published application.

## Status, renewal proof and stop

```bash
sudo systemctl status maverick-external-apps.service maverick-external-apps-tls.timer
sudo journalctl -u maverick-external-apps-tls.service -n 30 --no-pager
sudo certbot renew --dry-run --non-interactive --no-random-sleep-on-renew \
  --config-dir /var/lib/maverick/external-apps-tls/config \
  --work-dir /var/lib/maverick/external-apps-tls/work \
  --logs-dir /var/lib/maverick/external-apps-tls/logs
# Stop future issuance/renewal; this does not revoke already served content:
sudo systemctl disable --now maverick-external-apps-tls.timer
sudo systemctl stop maverick-external-apps-tls.service
# Revoke content without touching Core or other apps:
sudo systemctl disable --now maverick-external-apps.service
```

Do not remove the dedicated nginx catch-all while DNS still points here; retain
fail-closed routing. Supervisor loss expires public authority within 10 seconds.
Certificates alone confer no access. Resume by verifying prerequisites and enabling
the two units again. Never disable the shared host's unrelated Certbot timer.

The former sslip.io profile is retired. Its certificate renewal and uniquely
scoped DNS-01 port-53 firewall/tag must be removed only after migration. Retain an
HTTP-close/TLS-reject tombstone for its old namespace while that DNS still resolves
here, so old public links cannot fall through to the private default host.
