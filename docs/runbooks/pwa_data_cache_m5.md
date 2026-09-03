# PWA read-model cache M5 pilot operations and acceptance

This runbook covers the first M5 app-owned read-model adapters: Website Studio,
Storage catalog, App Store catalog, and Fitness Coach. It does not enable a
network-absence product mode, cache a mutation or authority decision, or opt in
Calendar, Chat, CRM, or Mail. The global gate and every app gate remain off by
default; Safari, Dock, and iPhone/Home Screen evidence remains a release gate.

The normative resource inventory is
`docs/product/pwa_cache_resource_inventory.v2.json`. Shared store, lifecycle,
retry, quota, and cleanup mechanics remain owned by `@maverick/pwa-cache` and
are operated with `docs/runbooks/pwa_data_cache_m3.md`.

## Parent-mediated boundary

Base Shell creates `PwaDataCacheBroker` with the freshly authenticated user,
workspace, and bounded access lease. An isolated app frame opens one private
`MessageChannel`; the shell accepts it only when all of these match:

1. the registered frame window and its exact isolated origin;
2. the mounted app id;
3. a fixed app/resource declaration and exact resource schema revision;
4. the global `MAVERICK_FEATURE_PWA_DATA_CACHE` gate; and
5. the matching `MAVERICK_FEATURE_PWA_APP_CACHE_<APP_ID>` gate.

The app never receives a shell IndexedDB handle, cache principal, access lease,
or policy capability. The shell asks the accepted frame to perform the
app-specific conditional server read, and the frame returns only an
app-sanitized read model or redaction-safe error classification over the
private port. Base Shell applies policy v2, byte limits, TTL, quota, lifecycle,
and a second plain-JSON validation before storage. A missing or disabled broker
falls back to one normal server read.

`maverick.app.data-changed` is accepted only from the shell or the exact frame
registered for the declared owner app. Logout, user/workspace transition,
`401`, and `403` use the M3 durable cleanup path and cancel accepted work.
Cached catalog or content data is never used to authorize launch, install,
write, publish, provider, capability, or confirmation actions.

## Pilot resource contracts

| App / resource | Policy | Fresh / expiry | Entry / scope | Stable validator | Invalidation |
|---|---|---:|---:|---|---|
| Website Studio `site-snapshots` / schema `website-studio.site-snapshots.v2` | `workspace_internal`, `app_reference`, reviewed `cache` | 60 s / 24 h | 2 MiB / 16 MiB | SHA-256 of the complete version map; `known_revision/not_modified` | source, working-state, navigation, preview, activity, settings, view-selection |
| Storage `file-catalog` / schema `storage.file-catalog.v1` | `workspace_internal`, `attachment`, reviewed `cache` | 30 s / 24 h | 256 KiB / 16 MiB | SHA-256 canonical catalog revision; `known_revision/not_modified` | files, drive-connections, view-state |
| App Store `catalog` / schema `app-store.catalog.v1` | `public`, `app_reference`, `cache` | 300 s / 24 h | 1 MiB / 4 MiB | authorized catalog SHA-256 plus strong `ETag` / `If-None-Match` | conditional revalidation on every read |
| Fitness Coach `sanitized-bootstrap-and-thumbnails` / schema `fitness-coach.sanitized-bootstrap-and-thumbnails.v1` | `personal_data`, `app_reference`, `session` | 300 s / 24 h | 512 KiB / 16 MiB | bootstrap `state_version`; thumbnail SHA-256 | workouts, exercises, runs, view-state; media identity includes Storage app and source version |

All four resources explicitly allow stale-but-unexpired rendering and select
revalidation on every warm read. Expired entries are misses and keep the
existing app loading component visible. An unchanged response refreshes only
metadata; it does not rewrite the payload. A changed response is applied
through the same normal view used for a server result.

### Website Studio

`workspace_snapshot` returns the existing segmented version map plus a stable
SHA-256 revision. The app and sitemap widget hash the requested site/route into
an opaque entity id. Old `sessionStorage` snapshots are sanitized and supplied
only as migration seeds; they are never painted directly and are deleted only
after the parent verifies the scoped commit. Snapshot values reject malformed
project/navigation shapes, credentials, signed URLs, object URLs, and local or
streaming paths.

### Storage

Only canonical first-page catalog reads are cached. Synchronous refreshes and
later pages remain direct server reads. The persisted model includes bounded
file/folder metadata and the view state, but removes remote locators, local
server paths, credential material, signed/object/stream/download URLs, and the
volatile inventory timestamp. Safe HTTPS Drive web links may remain. File bytes
and eligible preview bytes continue to use the separate M4 contract; OAuth,
Drive credentials, temporary archives, and control state are not part of this
resource.

### App Store

`GET /api/app-store/apps` authorizes the session before evaluating
`If-None-Match`, returns `Cache-Control: private, no-cache` and `Vary: Cookie`,
and emits an empty `304` for the exact authorized representation. Only the
catalog is cached. Pinned apps, installations, workspace membership, server
apps, publication state, and every install/uninstall action remain fresh server
state. Cached rows are read-only until those authority inputs complete.

### Fitness Coach

`app.bootstrap` accepts `known_revision` and returns a minimal `not_modified`
response. The existing scoped bootstrap `sessionStorage` entry and legacy
thumbnail store are quarantined as migration inputs; neither can paint before
parent confirmation. A newly captured thumbnail may render in the current page
while it is offered to the broker, but no second local cache is written.
Personal data remains `session` policy until a separate privacy approval
explicitly permits persistence.

## Feature flags and rollout

Effective enablement requires both flags:

```text
MAVERICK_FEATURE_PWA_DATA_CACHE=1
MAVERICK_FEATURE_PWA_APP_CACHE_WEBSITE_STUDIO=1
MAVERICK_FEATURE_PWA_APP_CACHE_STORAGE=1
MAVERICK_FEATURE_PWA_APP_CACHE_APP_STORE=1
MAVERICK_FEATURE_PWA_APP_CACHE_FITNESS_COACH=1
```

Do not enable all app flags at once. Recommended order is Website Studio,
Storage, App Store, then Fitness Coach. For each app:

1. deploy code with both gates off and verify the server-first path;
2. enable the global gate and only that app gate in a test workspace;
3. reload the authenticated shell so its registry and broker use the new gate;
4. exercise cold miss, warm fresh hit, stale hit, changed and unchanged
   revalidation, mutation event, expiration, `401/403`, logout, user/workspace
   switch, quota denial, IndexedDB denial, and cache clear;
5. compare normal layout and actions between equivalent cache and server
   results; and
6. record aggregate request/byte/time results and required physical-device
   evidence without record ids, URLs, payloads, or principal identifiers.

Calendar and Chat remain the next M5 tranche after pilot stability and privacy
review. CRM and Mail remain denied pending their explicit privacy gates.

## Automated preflight

Run bounded workers where supported:

```bash
npm --prefix packages/pwa-cache run typecheck
npm --prefix packages/pwa-cache test -- --maxWorkers=1
npx --prefix apps/base-shell/frontend vitest run src/pwaDataCacheBroker.test.ts --maxWorkers=1
npm --prefix apps/base-shell run build
npm --prefix apps/website-studio run build
npm --prefix apps/storage test -- --maxWorkers=1
npm --prefix apps/storage run build
npm --prefix apps/app-store run test:content-hash
npm --prefix apps/app-store run build
npm --prefix apps/fitness-coach test -- --maxWorkers=1
npm --prefix apps/fitness-coach run build
python3 scripts/test_suite.py --level fast
```

Also run the focused backend tests for the four validator contracts and use the
official `maverick app <app-id> frontend build --json` command for every changed
frontend before a mounted acceptance pass.

## Rollback

Disable the affected per-app flag first. Disable
`MAVERICK_FEATURE_PWA_DATA_CACHE` to stop every structured adapter. Reload or
restart the shell/backend as required by the deployment environment. A disabled
adapter performs its ordinary server-first read; it does not show a cache
status or alternate UI. Existing entries remain inaccessible and may be
removed with the bounded Settings **Clear cache** lifecycle. Never clear the
whole browser origin, the M2 shell Cache API, unrelated IndexedDB databases, or
M4 OPFS bytes as an M5 rollback shortcut.

Rollback immediately if an app can read another scope, a legacy entry paints
without parent confirmation, a cached value enables an authoritative action,
`401/403` does not block and clean the applicable copy, a signed URL or secret
appears in persisted data, an expired entry renders, or cache failure prevents
a successful server response.
