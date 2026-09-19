# External Apps

One sealed first-party app for small, public, immutable static/SPA releases.
It is **not** a general application server or a replacement for Website Studio.
Repository decision: [`external_apps_v1.md`](../../docs/architecture/external_apps_v1.md).

## Use

1. Install/enable the platform app through Maverick App Store. Do not register it
   as a workspace-local app. Select an enabled Website Studio provider for the
   `static-exporter` dependency in App Store.
2. An administrator configures the deployment domain in External Apps. Saving
   this value does **not** provision DNS, TLS, ingress or a public service.
3. Complete a passing static or Node build in Website Studio. PHP/SSR are rejected.
4. Enter site/build ids, name and static/SPA routing; prepare the publication.
5. Review URL, exact release digest, revision, size and replaced release. Confirm
   in the authenticated UI, then publish. All exported files become public.
6. Suspend blocks subsequent requests, including revalidation and retained asset
   URLs. Rollback prepares the retained previous release; it requires a new human
   approval. Archive retains history and cannot be republished in V1.

State (`draft`, `published`, `suspended`, `archived`) and HTTP health are separate.
Publishing verifies the real credential-free HTTPS endpoint and exact entrypoint
bytes after cutover. A failed probe conditionally restores the previous binding;
the candidate can briefly be visible before compensation. Downloads already
received cannot be revoked. The opaque URL is not authentication.

Only admins mutate; workspace members can read. UI approval is not an agent
`confirm:true` argument. CLI/MCP share the backend service but cannot approve.
Hosted Chat mutation admission remains Core-owned: an unadmitted runtime uses
the UI handoff, not a direct-file or policy bypass.

## Small, explicit limits

- Existing completed build; apply never rebuilds or silently picks a newer one.
- ZIP/base64 through the private dependency callback: 2 MiB ZIP, 8 MiB expanded,
  2 MiB/file, 512 files, compression ratio at most 100. Website's deterministic
  exporter stores entries uncompressed, so its effective bundle cap is 2 MiB.
- 100 publications and 1,000 retained release records per installation in a
  workspace; 15-minute plans. Preparation stops at 2,000 plans/10,000 operations.
  Expired unused plans/releases and old unreferenced artifacts are reclaimed on
  preparation and lifecycle recovery; published history is retained.
- Closed MIME allowlist; no executable backend, secret delivery, private Maverick
  routes, service worker, external fetch, forms or embedded frames. Local JS/CSS
  and inline scripts/styles are supported. Static bundles must be self-contained.
- 64 explicit workspace mounts, 32 concurrent public connections, 32 MiB content
  cache. Authority is reread before every request/304; no independent proxy cache.

## Operator deployment (not activated by installation)

Production requires Linux, the system Python under `/usr/bin` and bubblewrap with
user namespaces available. Unsupported confinement fails closed; there is no
unconfined fallback. Use a dedicated registrable public domain separate from
Maverick's, not merely a sibling subdomain. Platform session cookies must still
be host-only, not parent-domain cookies.

The private foreground supervisor reads the **same canonical control-store
configuration as the backend**, without bootstrapping or restarting it. It checks
live workspace/app/source authority and recovers interrupted app-owned intents
under OS locks. It launches a no-network, no-credentials child with only read-only
public artifact/binding mounts and a writable Unix-socket directory. Do not pass
whole workspace, repository or control-store directories to that child.

Follow the [activation runbook](deployment/README.md), including the independently
managed systemd unit, DNS-01 renewal, shared-nginx safety and stop path.
Review [`deployment/supervisor.example.json`](deployment/supervisor.example.json)
and [`deployment/nginx.example.conf`](deployment/nginx.example.conf). Replace the
example domain and certificate paths. The two service directories must be
dedicated, distinct, outside published trees, and accessible only to the operator
service account and the ingress group as appropriate. The supervisor needs read
access to canonical hosting state and write access to selected External Apps
data for crash reconciliation; it does not need write access to other apps.

After operator DNS/TLS/ingress setup, run in the foreground:

```bash
python3 scripts/external_apps_supervisor.py --config /etc/maverick/external-apps.json
```

An operator may manage this command in their normal service manager. This app
does not install/start a detached service. Stop with SIGTERM; serving authority
is revoked, and the confined child exits. A killed/stalled supervisor expires
authority in at most 10 seconds. Workspace close, app disable/uninstall or an
invalid deployment removes the mount on the next successful authority refresh;
failure to refresh also expires it. An app-level suspend is checked synchronously
at the next request admission. Unknown hosts never reach private Maverick routes.

## Deployment acceptance

Do not call an installation Internet-ready until all of these are verified:

1. Wildcard DNS and a valid TLS certificate for the configured managed hosts.
2. The dedicated ingress routes only to the public Unix listener, strips
   credentials, disables independent caching and preserves release/hash headers.
3. Anonymous HTTPS from outside the host loads a synthetic static site and a
   genuine built SPA, including assets, lazy chunks and a deep link.
4. Failed verification preserves/restores the prior release. Suspend/rollback,
   stale ETags, process interruption and supervisor loss behave as documented.
5. Disabled/uninstalled app and closed workspace stop serving; the public child
   cannot read private catalogs, credentials or reach host loopback/network.

These are deployment gates, not effects of checking a domain field. In particular,
isolated test success does not prove wildcard DNS/TLS or Internet reachability.

## Verification

### App-owned checks

From the repository root:

```bash
python3 -m unittest discover -s apps/external-apps/tests -p 'test_*.py' -v
EXTERNAL_APPS_CONFINEMENT_TEST=1 EXTERNAL_APPS_VITE_TEST=1 \
  python3 -m unittest discover -s apps/external-apps/tests -p 'test_*.py' -v
EXTERNAL_APPS_INGRESS_TEST=1 \
  python3 -m unittest discover -s apps/external-apps/tests -p test_deployment.py -v
python3 -m unittest discover -s apps/website-studio/tests -p test_external_export.py -v
python3 scripts/check_unused_imports.py apps/external-apps scripts/external_apps_supervisor.py
```

The Vite proof needs the frontend's installed Node dependencies and npm cache or
registry availability for Website's isolated `npm ci`. Confinement proof starts
only an ephemeral Unix listener in a temporary directory. No live app is installed
and no backend restart is required. UI checks use one Chromium worker:

```bash
maverick app external-apps frontend build --json  # once installed, official build
npm --prefix apps/external-apps run test:ui
```

If Chromium is installed in a shared cache, set `PLAYWRIGHT_BROWSERS_PATH` to it.
Before live installation, the same official frontend build service can be invoked
with an isolated test store/workspace. CLI/MCP discovery uses `list`/`inspect`;
the executable operation manifest is the default `external-apps` command or
`external_apps` MCP action, without returning artifact bytes.

## SDK Flow

Source was created with the official App SDK. Validate with
`maverick core cli run core.app-sdk.validate --app-id external-apps --json` or
the canonical `core.app_sdk.service.validate_app_source` API before installation.
The frontend uses the official isolated-frame assets/manifest plugins and the
Core frontend build service; lifecycle hooks initialize only app-owned data.

## Contract Notes

No widgets, skills, reference entities, persisted view state, workspace export
or workspace import are declared in V1. The common reference manifest is empty
schema metadata, not a public catalog. No secrets or anonymous Core routes are
requested. The portable app and operator-deployed Linux public service have
separate lifecycle responsibilities; disabling the app never starts a service.
