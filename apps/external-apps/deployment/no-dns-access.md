# Deployment without DNS-provider access

## Decision and limits

Use an IP-based public DNS namespace outside Maverick's registrable domain,
with a **real, privately held wildcard certificate**. No tunnel, public private
key, per-publication certificate, on-demand TLS server, or anonymous Core route.
The app/publication protocol is unchanged.

[sslip.io / nip.io](https://nip.io/) resolve hostnames containing an IP to that
address. Their [DNS-01 delegation](https://nip.io/experimental.html) delegates
`_acme-challenge.<namespace>` to the embedded IP. Verify this behavior against
the live authoritative servers before relying on it. This delegation is labelled
experimental by the provider: it can change and is not an availability guarantee.

The [Certbot standalone DNS plugin](https://github.com/siilike/certbot-dns-standalone)
answers the delegated validation on TCP/UDP 53 **only while Certbot runs**.
It is not a recursive DNS server and needs no DNS-provider API token. The host's
normal loopback resolver stays untouched. Existing Certbot scheduling owns renewal;
there is no additional permanent DNS daemon or app-owned renewal scheduler.

This profile trades domain ownership for an external DNS dependency. Keep the IP
reserved, monitor renewal failures/expiry, and retain the cloud firewall rule.
Provider outage, a changed delegation, blocking/abuse policy or loss of the IP
can break serving/renewal. A user-owned separate domain remains preferable for
long-term production. V1 does not migrate domains after publications exist;
changing to a branded domain later requires an explicit migration, not an
automatic alias. Shared DNS names must never receive private Maverick cookies.

## Verified host configuration — 2026-09-19

| Resource | Active value |
| --- | --- |
| Public namespace | `apps.34-17-71-112.sslip.io` |
| Public DNS | Base + arbitrary single-label subdomains resolve to `34.17.71.112` |
| IP reservation | Existing `loopino-agent-vm`, `europe-west12`; no new IP purchased |
| Certificate | Let's Encrypt, base + `*.apps.34-17-71-112.sslip.io` |
| Initial expiry | 2026-12-18; renewal managed by enabled `certbot.timer` |
| Certificate lineage | `/etc/letsencrypt/live/maverick-external-apps/` |
| ACME DNS bind | `10.210.0.3:53` and loopback `[::1]:53` |
| Cloud firewall | `maverick-external-apps-acme-dns`, TCP/UDP 53, target tag `maverick-external-apps-acme` on this VM only |
| Public service | `maverick-external-apps.service`, enabled, non-root supervisor + confined child |
| Configuration | `/etc/maverick/external-apps.json`, workspace `default`, local app `external-apps` |
| nginx | Separate `sites-available/maverick-external-apps.conf` and `sites-enabled` symlink |
| Provider | Installed Website Studio selected through official Core dependency CLI |

The app was SDK-validated and its single platform source registered through
Core's canonical `register_app_source_from_contract` API: the running CLI did not
expose a platform-registration command. No bulk bootstrap or direct JSON edits.
Installation, dependency selection, domain configuration and frontend build then
used the authenticated official CLI. The catalog is empty: no user's site was
published or UI approval fabricated.

Only two distro packages were added (`python3-certbot-dns-standalone` 1.1-2 and
`python3-dnslib` 0.9.25-1); no existing packages were upgraded and no services
restarted by the package operation. Private keys and ACME account state remain
root-owned under `/etc/letsencrypt`, outside Git and all public mounts.

## Reproduce or maintain

1. Confirm ownership of the server/IP and a reserved public IPv4 address.
   Check fresh wildcard A/AAAA answers and the delegation, for example:

   ```bash
   dig +short A probe.apps.34-17-71-112.sslip.io
   dig @ns-00.nip.io TXT _acme-challenge.apps.34-17-71-112.sslip.io
   ```

2. Permit only TCP/UDP 53 to the intended VM in its cloud firewall. Do not widen
   existing rules or change the local resolver. Bind the plugin to the VM's
   actual interface address, not a NAT public IP or `0.0.0.0`.
3. Install the supported distro plugin after a package dry run. Perform a
   staging issuance first with separate config/work/log directories. The initial
   proof used `/var/lib/maverick/external-apps-acme-staging/` and
   `/var/log/maverick-external-apps-acme-staging`.
4. Install the reviewed `renew-nginx.sh` as root-owned mode 0755 at
   `/usr/local/libexec/maverick-external-apps-renew-nginx`. Issue the real cert:

   ```bash
   sudo certbot certonly --non-interactive --agree-tos \
     --authenticator dns-standalone --preferred-challenges dns \
     --dns-standalone-address=10.210.0.3 \
     --dns-standalone-ipv6-address=::1 --dns-standalone-propagation-seconds=5 \
     --cert-name maverick-external-apps \
     -d apps.34-17-71-112.sslip.io -d '*.apps.34-17-71-112.sslip.io' \
     --deploy-hook /usr/local/libexec/maverick-external-apps-renew-nginx
   ```

   This host already had a production ACME account. On a new host, configure
   the operator's account/contact deliberately; do not invent an email address.
5. Follow the [normal service/ingress runbook](README.md), using the real domain
   and lineage above. Wait for the nginx reload to complete before the TLS probe:
   immediately after its signal, old workers can still have the previous config.
6. Test the persisted renewal configuration and actual deploy hook:

   ```bash
   sudo certbot renew --cert-name maverick-external-apps --dry-run \
     --run-deploy-hooks --non-interactive --no-random-sleep-on-renew
   systemctl list-timers certbot.timer
   ```

   The hook skips other lineages, validates the complete nginx configuration,
   and reloads nginx only on success. It never restarts Core. It skips the first
   issuance if the dedicated ingress file is not yet installed. The shared host
   already had duplicate-name/deprecated-http2 warnings; `nginx -t` succeeds.
   Those unrelated virtual hosts are deliberately not rewritten here.

## Evidence and remaining publication gate

Live staging issuance, trusted production wildcard issuance and simulated renewal
with the deploy hook succeeded. Public-IP HTTPS from this host validates the
certificate normally and returns 404 for unknown hosts/private paths, without
cookies or a private-platform fallback. Stopping only the new service returns
503; restarting restores 404 and a fresh admitted workspace projection. The
public worker group can reach its Unix socket. The service survived the separately
initiated Core restart reported during this task; this deployment never restarted
Core itself. A peer-disconnect/readiness log loop found during activation was
fixed and covered by tests.

ACME proves external DNS reachability. The web-fetch tool could not fetch these
404 URLs, so it is **not** evidence of an independent external browser test.
Internet acceptance of an actual static/SPA publication still requires the
specific synthetic plan to be approved in the authenticated UI, then verified
from outside the host. Do not equate active hosting or fixture tests with that
final per-release proof.

Status/stop remains `systemctl status` / `systemctl disable --now
maverick-external-apps.service`. Keep the public nginx host to fail closed while
DNS still resolves here. Remove the exact ACME firewall rule/tag only when this
certificate no longer needs renewal; never delete a shared rule or the IP
reservation. Retain app data and private certificate material during rollback.
