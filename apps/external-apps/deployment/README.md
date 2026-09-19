# Public hosting activation

This is an operator procedure, not a second installer or an app-side daemon.
Changing the app's domain field does not activate any of these resources.
Do not restart Maverick Core to install this independent service.

## 1. Confirm the public domain and DNS authority

Prefer an operator-owned registrable domain **different from Maverick's**.
`apps.example.com` below is only a placeholder. Do not reuse private app-frame
or sidecar hosts, buy a domain, or repoint existing records implicitly.
When DNS-provider access is unavailable, use the explicitly reviewed
[IP-based DNS profile](no-dns-access.md), with its external-dependency tradeoffs.

Create `apps.example.com` and `*.apps.example.com` A records for this ingress.
Add AAAA only if IPv6 actually reaches this ingress. Verify both with a fresh,
unallocated hostname; testing one existing name does not prove wildcard DNS.
Every returned address must be the intended ingress. Keep any CDN response cache
disabled: serving authorization must be revalidated by the public runtime.

## 2. Provision and renew TLS independently

Obtain a trusted certificate with SANs `apps.example.com` and
`*.apps.example.com`. For Let's Encrypt, wildcard issuance uses
[DNS-01, not HTTP-01](https://letsencrypt.org/docs/challenge-types/).
Use the DNS provider's supported ACME plugin with narrowly scoped credentials,
or an externally managed certificate with an automated delivery/renewal path.
Never put DNS credentials, private keys, or Core's `.env` in this app or Git.
Do not issue certificates before the operator has identified the actual domain.

For Certbot, prefer a separate `maverick-external-apps` lineage. Point nginx at
its `fullchain.pem` and `privkey.pem`; do not copy keys into the repository or
change existing Maverick certificate lineages. Validate SANs, validity and key
matching before enabling the virtual host. A manual one-time TXT challenge is
not a renewal strategy.

Configure a lineage-scoped deploy hook that runs `nginx -t` followed by
`systemctl reload nginx` only after successful renewal of this certificate.
Test renewal with the selected provider's staging/dry-run flow before activation.
The ACME client owns renewal; neither Core nor the public runtime needs DNS keys.

## 3. Prepare the app through Maverick

Install/enable the sealed **platform** External Apps source using App Store,
select Website Studio as `static-exporter`, then configure the chosen domain in
the authenticated External Apps UI. Do not edit control-plane records or create
a workspace-local copy to bypass a missing catalog registration. If the running
catalog does not yet expose the platform source, resolve registration through
the supported hosting flow in a safe operational window; do not bootstrap or
restart the active chat as a shortcut.

No existing site is published by deployment setup. Publication still requires a
specific passing build, reviewed immutable plan and authenticated human approval.

## 4. Render and review the service files

Copy `supervisor.example.json` to a staging directory outside live `/etc`.
Set the actual domain and only the explicitly selected workspace/local app ids.
Keep its two `/run/maverick-external-apps-*` paths aligned with the unit and nginx.

Render `maverick-external-apps.service.example` into
`maverick-external-apps.service`, replacing every `{{...}}` token:

| Token | Actual host value |
| --- | --- |
| `INSTALL_ROOT` | Canonical Maverick checkout, without symlink ancestors |
| `SERVICE_USER` | Trusted backend service account, not root |
| `SERVICE_GROUP` | Backend's operating group for app data/control-store locks |
| `INGRESS_GROUP` | nginx worker group, commonly `www-data` |
| `CONTROL_STORE_ROOT` | Absolute active canonical JSON store root |
| `APP_DATA_ROOT` | Exact existing `workspaces/<id>/data/<local_app_id>` root |

The template is deliberately for the **JSON adapter**. Confirm the running
backend's adapter/path through `core.persistence.status` after official CLI
discovery. Never silently use the default store if the backend uses another one.
For multiple explicitly selected workspaces, add one `ReadWritePaths` per app
data root. Do not grant whole-workspace or whole-control-store write access.

JSON read operations use the canonical shared lock files; the unit exposes only
the three existing lock files as writable, not their JSON collections. App
recovery can write its own data. A missing lock/data directory is a setup error,
not a reason to remove the sandbox. Keep service persistence settings aligned
with any later backend adapter migration. Mongo deployment needs a separately
reviewed unit: the canonical Mongo collection factory also ensures indexes.

Systemd creates the runtime directories with the service user and ingress group.
The socket inherits that group and allows group connection; no `chmod 777` or
global user/group membership change is needed. The public child still runs inside
bubblewrap without host networking, private mounts or inherited credentials.
Do not add namespace restrictions that prevent bubblewrap, or an unconfined
fallback. Use system Python under `/usr/bin` as declared by the unit.

## 5. Enable only the independent service and public virtual hosts

Before installing, verify no other operator owns these exact destination files.
Keep a private backup of any pre-existing file you are explicitly replacing.

```bash
# Run against the reviewed staged unit, with no remaining {{...}} placeholders.
systemd-analyze verify ./maverick-external-apps.service
sudo install -d -m 0755 /etc/maverick
sudo install -m 0644 ./external-apps.json /etc/maverick/external-apps.json
sudo install -m 0644 ./maverick-external-apps.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now maverick-external-apps.service
sudo systemctl status maverick-external-apps.service --no-pager
sudo -u www-data curl --unix-socket /run/maverick-external-apps-listener/public.sock \
  -sS -o /dev/null -w '%{http_code}\n' -H 'Host: invalid' http://localhost/
```

Replace `www-data` with the real ingress user. The anonymous socket probe must
return **404**, not fail to connect. That proves listener/permissions, not a
mounted workspace or Internet readiness. Inspect the fresh projection's namespace
list against the selected app's deployment metadata before proceeding; an empty
list means no app is admitted even if the listener is healthy.

Render `nginx.example.conf` with the actual domain/certificate paths. Install it
as a **new dedicated file** in the host's normal nginx include directory; on
Debian-style hosts, use a reviewed `sites-available` file and one `sites-enabled`
symlink. Do not run the general Maverick installer or overwrite its virtual hosts.
The template has no `default_server`, so it does not take over shared port 443.
It covers the base and wildcard names, closes plain HTTP, forwards only required
request headers and fails 503 if the public Unix listener is lost. It has no
private ASGI fallback, including on upstream errors.

Record Core's PID/start time and check private/public Maverick health first.
Run `sudo nginx -t` against the **complete live configuration**. Only on success,
use `sudo systemctl reload nginx` (not restart). Recheck Maverick health and
unchanged Core PID/start time. A failed check blocks activation; restore only
this deployment's file/symlink, validate again, then reload. Never replace another
agent's nginx configuration or reload a known-invalid shared configuration.

## 6. Acceptance and stop path

From outside the host, verify a fresh wildcard name resolves and negotiates
trusted TLS without `-k`; an unknown publication must return 404, not Maverick's
login or another site's content. Publish only an approved synthetic static site
and genuine SPA, then complete the [deployment acceptance checks](../README.md#deployment-acceptance).
Local fixture certificates and loopback tests are not evidence of public DNS/TLS.

```bash
sudo systemctl status maverick-external-apps.service --no-pager
sudo journalctl -u maverick-external-apps.service -n 50 --no-pager
# Revoke the service without touching Core, nginx, or other apps:
sudo systemctl disable --now maverick-external-apps.service
```

Stopping expires the projection and terminates the confined child. Leave the
dedicated nginx virtual hosts in place to fail closed with 503; removing them
while DNS still points here could send those hostnames to a private default host.
Data and publication history remain intact. Re-enabling after verification uses
`systemctl enable --now maverick-external-apps.service`.

## Verification and current deployment status

`EXTERNAL_APPS_INGRESS_TEST=1 python3 -m unittest discover -s apps/external-apps/tests -p test_deployment.py -v`
runs a foreground-only nginx on ephemeral loopback ports with a disposable test
certificate and Unix upstream. It verifies TLS, shared-host preservation,
credential stripping, HEAD/ETag forwarding, denied writes and fail-closed outage.
It never changes live nginx or systemd.

Initial inspection found no dedicated domain/certificate or live app registration.
On 2026-09-19, after explicit user authorization to proceed without DNS-provider
access, the [IP-based profile](no-dns-access.md) was activated with a genuine
wildcard certificate, automatic renewal, installed app and isolated systemd
service. No publication was automatically approved. The linked evidence separates
live infrastructure verification from the remaining per-release Internet gate.
