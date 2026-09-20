# CRM live public service

This adapter serves the real CRM frontend and database, not a snapshot. Public
read-only access exposes CRM-owned records and exports. Explicit public-write
mode also allows native CRUD, imports and local workflows. It never exposes
Maverick auth, hosting administration, provider execution, provider approvals,
full backup restore or other apps' APIs. Existing CRM-local integration snapshots
remain readable. Do not call this anonymous access to Mail or Storage.

The private CRM remains unchanged: its navigation lives in the shell sidebar.
Only the public document mounts the same navigation component itself. Its hash
routes work on reload, public search does not persist private view preferences,
and display reads do not use a private PWA cache/session bridge.

## Activation (operator, Linux)

Run tests/builds before activation. Needs `/usr/bin/python3`, bubblewrap with user
namespaces, nginx and certbot. No unconfined fallback. No Core restart required.
The following example assumes the existing External Apps HTTP-01 ingress and
DNS for `*.apps.<installation-domain>`. On another installation provision those
first; never silently substitute another domain.

1. Resolve the enabled platform CRM binding in the chosen workspace. Create
   `data/crm/external-hosting/deployment.json` with the operator-attested
   `{"installation_domain":"maverick.example.com"}`. Create `access.json` with
   `{"enabled":false,"access":"read-only","revision":0}`. This metadata is
   non-secret and app-owned. Settings never chooses a hostname or workspace.
2. Write `/etc/maverick/crm-public.json` (root-owned) with `installation_domain`,
   `workspace_id`, `state_directory=/run/maverick-crm-public-state` and
   `listener_directory=/run/maverick-crm-public-listener`.
3. Render `service.example` with the canonical repository/workspace and review
   OS account/group and canonical control-store configuration. Install it as
   `maverick-crm-public.service`. Do not borrow Core secrets/environment. The
   private supervisor reads hosting state; the public child receives only its
   CRM closure. Read-only mounts enforce read-only data at filesystem level.
4. Obtain the **exact** certificate, in a dedicated certbot state directory:

   ```sh
   certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
     --webroot -w /var/lib/maverick/external-apps-acme \
     --config-dir /var/lib/maverick/crm-public-tls/config \
     --work-dir /var/lib/maverick/crm-public-tls/work \
     --logs-dir /var/lib/maverick/crm-public-tls/logs \
     --cert-name crm-public -d crm.apps.<installation-domain>
   ```

   Parent TLS state must be root-owned mode 0700. Install the supplied renewal
   unit/timer as `maverick-crm-public-renew.service/.timer`. Do not change shared
   certbot accounts, timers or private Maverick certificates.
5. Render `nginx.example.conf` with the installation domain. Back up existing
   ingress first, install as a separate exact-host site, run `nginx -t`, then
   **reload**, not restart, nginx. Unknown namespace hosts must still fail closed.
6. Enable the operator service and renewal timer. Open CRM → sidebar settings →
   **Superfici esterne**, review access and confirm. An operator performing an
   explicitly user-requested deployment may initialize `access.json` to enabled
   read-only with revision 1; record this in the work log rather than fabricating
   a Core user/runtime approval. Public write mode requires separate consent.
7. Verify anonymous HTTPS document/assets, real CRM reads, denied writes in
   read-only mode, denied other-app/hosting routes, browser navigation/mobile,
   supervisor expiry and suspend. No data is fetched through Core in this mode.

## Stop / rollback

```sh
systemctl status maverick-crm-public.service maverick-crm-public-renew.timer
systemctl disable --now maverick-crm-public.service
systemctl disable --now maverick-crm-public-renew.timer
```

App settings disable blocks the next admitted request. Supervisor loss expires
authority in at most 10 seconds; mode changes revoke the old child's projection
before replacing it. Requests already executing/downloaded bytes are not revoked.
Keep a rejecting exact ingress or the existing namespace TLS rejection after
stopping: never leave DNS pointing at a private default virtual host. CRM data is
not deleted on disable/stop, and other app services/Core are not restarted.

## Verification

```sh
CRM_PUBLIC_CONFINEMENT_TEST=1 /usr/bin/python3 -B -m unittest discover \
  -s apps/crm/tests -p 'test_*.py' -v
maverick app crm frontend build --json
```

The service and listener have independent bounded memory/process/request limits.
HTTP responses are no-store, noindex, frame-denied, exact-host and path-allowlisted;
JSON POSTs require the exact public Origin, and ingress strips credentials.
This is intentional public data access, not protection by an unguessable URL.
