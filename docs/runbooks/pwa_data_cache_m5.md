# PWA read-model cache M5 pilot operations and acceptance

This runbook covers all eight approved M5 apps: Website Studio, Storage, App
Store, Fitness Coach, Calendar, Chat, CRM and Mail. Product/privacy approval is
recorded in `docs/product/pwa_cache_completion_decision_2026-09-05.md`; the
resource-specific adapters implement its limits. Approval does not enable a
network-absence mode, mutations, or authority from cache. Global and app gates
remain off by default; physical-device evidence and controlled rollout remain
release gates.

The normative resource inventory is
`docs/product/pwa_cache_resource_inventory.v2.json`. Base Shell consumes the
machine-readable runtime subset in
`apps/base-shell/frontend/src/pwaDataCacheResourceDeclarations.v1.json`; the
operational audit requires an exact bidirectional match for every row carrying
a runtime schema revision. Shared store, lifecycle, retry, quota, and cleanup
mechanics remain owned by `@maverick/pwa-cache` and are operated with
`docs/runbooks/pwa_data_cache_m3.md`.

## Parent-mediated boundary

Base Shell creates `PwaDataCacheBroker` with the freshly authenticated user,
workspace, and bounded access lease. Every isolated app and widget frame is
registered with its real owner app id, active workspace, and opaque
authenticated shell-session generation, and may open a private
`MessageChannel`; the shell accepts it only when all of these match:

1. the registered frame window and its exact isolated origin;
2. the registered workspace/session generation and the current broker scope;
3. the registered owner app id and requested mounted app id;
4. a fixed app/resource declaration and exact resource schema revision;
5. the global `MAVERICK_FEATURE_PWA_DATA_CACHE` gate; and
6. the matching `MAVERICK_FEATURE_PWA_APP_CACHE_<APP_ID>` gate.

The app never receives a shell IndexedDB handle, cache principal, access lease,
or policy capability. The shell asks the accepted frame to perform the
app-specific conditional server read, and the frame returns only an
app-sanitized read model or redaction-safe error classification over the
private port. Base Shell applies policy v2, byte limits, TTL, quota, lifecycle,
and an app-specific closed display sanitizer before storage. A missing or
disabled broker falls back to the same validated server read; only its fixed
idempotent HTTP request may retry, never the arbitrary app loader.

`maverick.app.data-changed` is accepted only from the shell or an exact app or
widget frame whose registered owner matches the declared owner app. Resource
aliases (including Storage `files`, `drive-connections`, and `view-state`) are
mapped only after that owner check. Logout and user/workspace transition use
the M3 durable cleanup path, rotate the shell-session generation, synchronously
unmount frames from the previous scope, and cancel accepted work. A late frame
from the old scope receives an immediate unavailable result and cannot inspect
a warm entry belonging to the new workspace. App and widget fan-out handlers
also compare the sender's registered owner with the declared owner; only an
exact top-level shell message may fan out across owners. A `401` or `403` from a
brokered network read additionally tells AppShell to clear authenticated UI and
unmount every app/widget iframe immediately; reauthentication mounts fresh
documents after cleanup, preventing an earlier warm paint from remaining in
memory or the DOM.

AppShell treats every session reload or logout as a publication barrier. It
synchronously withdraws the broker principal and frame scope before awaiting
network or durable cleanup, serializes every lifecycle mutation, and publishes
a candidate authenticated session only after lifecycle transition and registry
load succeed. A concurrent `401/403` invalidates the pending load, so its later
cleanup completion cannot remount that session. Logout never waits for a second
session fetch to remove authenticated frames.

Workspace switch/create follows the same barrier before the mutation reaches
Core: cancel the active load, synchronously unmount frames, dispose the
structured broker and Storage file broker, call the workspace endpoint, run the
lifecycle transition, load the scoped registry, then publish. The workspace
switcher component must never call the API directly.

All parent-side authorization observations use the shared shell revocation
channel: ordinary shell APIs, both `/api/pwa/config` projections, structured
broker reads, Storage file broker reads, and isolated-frame launch. Every
observation repeats the synchronous AppShell notification and iframe teardown,
even if an earlier cleanup has not settled. Coalesce only the durable cleanup
promise, which remains serialized. Do not await that deletion inside an HTTP
request timeout window: an observed `401`/`403` must remain terminal HTTP rather
than becoming a transport timeout.
Cached catalog or content data is never used to authorize launch, install,
write, publish, provider, capability, or confirmation actions.

## Pilot resource contracts

| App / resource | Policy | Fresh / expiry | Entry / scope | Stable validator | Invalidation |
|---|---|---:|---:|---|---|
| Website Studio `site-snapshots` / schema `website-studio.site-snapshots.v2` | `workspace_internal`, `app_reference`, reviewed `cache` | 60 s / 24 h | 2 MiB / 16 MiB | SHA-256 of the complete version map; `known_revision/not_modified` | source, working-state, navigation, preview, activity, settings, view-selection |
| Storage `file-catalog` / schema `storage.file-catalog.v1` | `workspace_internal`, `attachment`, reviewed `cache` | 30 s / 24 h | 256 KiB / 16 MiB | SHA-256 canonical catalog revision; `known_revision/not_modified` | files, drive-connections, view-state |
| App Store `catalog` / schema `app-store.catalog.v1` | `public`, `app_reference`, `cache` | 300 s / 24 h | 1 MiB / 4 MiB | authorized catalog SHA-256 plus strong `ETag` / `If-None-Match` | conditional revalidation on every read |
| Fitness Coach `sanitized-bootstrap-and-thumbnails` / schema `fitness-coach.sanitized-bootstrap-and-thumbnails.v1` | `personal_data`, `app_reference`, approved `cache` | 300 s / 24 h | 512 KiB / 16 MiB | bootstrap `state_version`; thumbnail SHA-256 | workouts, exercises, runs, view-state; media identity includes Storage app and source version |
| Calendar `bounded-event-window` | approved personal `cache` | 60 s / 6 h | 1 MiB / 16 MiB | bounded interval/page SHA-256 | events, calendars, connections, view-state |
| Chat `projects-and-completed-messages` | approved personal `cache` | 30 s / 6 h | 1 MiB / 32 MiB | completed display/project/page SHA-256 | projects, threads, runtime-threads, messages, view-state; reconnect |
| CRM `lists-and-recent-records` | approved customer allowlist `cache` | 30 s / 6 h | 2 MiB / 16 MiB | closed display SHA-256 | records, schema, pipelines, view-state |
| Mail `thread-headers-snippets-and-bodies` | approved customer allowlist `cache` | 30 s / 1 h | 1 MiB / 16 MiB | closed display SHA-256 | threads, messages, connections, folders, labels, view-state |

All eight resources explicitly allow stale-but-unexpired rendering and select
revalidation on every warm read. Expired entries are misses and keep the
existing app loading component visible. An unchanged response refreshes only
metadata; it does not rewrite the payload. A changed response is applied
through the same normal view used for a server result.

### Website Studio

`workspace_snapshot` returns the existing segmented version map plus a stable
SHA-256 revision. The app and sitemap widget hash the requested site/route into
an opaque entity id. Old `sessionStorage` snapshots lack a verifiable user/workspace scope and are
deleted without reading or importing them. Only the current scoped broker or
server result can supply display data. Snapshot values reject malformed
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
response. Closed projections exclude media capabilities and unknown nested
fields. Legacy bootstrap/thumbnail browser storage is deleted without migration:
workspace/app keys did not attest user scope. New reads validate Core's frozen
frame context and the exact mounted app. A freshly captured bounded thumbnail
may render in the current page and seed the authenticated broker; there is no
parallel app-local persistent writer.

### Calendar, Chat, CRM and Mail

All four use SDK-owned fixed display reads and conditional SHA-256 revisions.
Calendar caches 500-event pages in a maximum 93-day interval and consulted event
details. Projects use 200-item pages; runtime thread pages and the last 50 turns
(up to 5,000 scanned events) yield only completed user/assistant text. The first
live snapshot replaces Chat's rendering-only cached events. Raw transcripts,
provider state and local send queues are never persisted; legacy namespaces are
purged without import. Live send state exists only until document teardown.

CRM caches recent records/lists, pipeline display and schema, but not workflow
proposals or authority. Mail caches mailbox/folder display, recent headers and
consulted message text. Rich HTML, attachment bytes and provider inputs are
live-only enhancements under their existing policy, not dependencies of warm
paint. All byte ceilings skip persistence for oversized otherwise valid results;
they do not silently truncate normal UI. Calendar/project pagination follows
conditional growth and shrink.

## Feature flags and rollout

Effective enablement requires both flags:

```text
MAVERICK_FEATURE_PWA_DATA_CACHE=1
MAVERICK_FEATURE_PWA_APP_CACHE_WEBSITE_STUDIO=1
MAVERICK_FEATURE_PWA_APP_CACHE_STORAGE=1
MAVERICK_FEATURE_PWA_APP_CACHE_APP_STORE=1
MAVERICK_FEATURE_PWA_APP_CACHE_FITNESS_COACH=1
```

M6 additionally permits deterministic workspace/user narrowing with
`<FLAG>_ROLLOUT_WORKSPACE_PERCENT` and `<FLAG>_ROLLOUT_USER_PERCENT`. These
cohorts only narrow an enabled flag; they never widen resource policy. Use the
sequence and fail-closed rules in `docs/runbooks/pwa_cache_operations_m6.md`.

Do not enable all app flags at once. Recommended order is Website Studio,
Storage, App Store, Fitness Coach, Calendar, Chat, CRM, then Mail. For each app:

1. deploy code with both gates off and verify the server-first path;
2. enable the global gate and only that app gate in a test workspace;
3. reload the authenticated shell so its registry and broker use the new gate;
4. exercise cold miss, warm fresh hit, stale hit, changed and unchanged
   revalidation, app- and widget-originated mutation events, cross-owner spoof
   rejection, expiration, warm-paint `401/403` iframe teardown, logout with a
   delayed request/cleanup, concurrent authorization failure during a delayed
   transition, user/workspace switch (including unpublished new scope during
   cleanup and old-frame rejection against a warm new-workspace cache), quota
   denial, IndexedDB denial, and cache clear;
5. compare normal layout and actions between equivalent cache and server
   results; and
6. record aggregate request/byte/time results and required physical-device
   evidence without record ids, URLs, payloads, or principal identifiers.

Calendar, Chat, CRM and Mail have approved resource-specific policies. No
further generic CRM/Mail privacy decision is pending. Technical regressions,
physical-device acceptance and cohort observation remain distinct release gates.

## Automated preflight

Run bounded workers where supported:

```bash
npm --prefix packages/pwa-cache run typecheck
npm --prefix packages/pwa-cache test -- --maxWorkers=1
npm --prefix apps/base-shell test -- src/pwaDataCacheBroker.test.ts --maxWorkers=1
npm --prefix apps/base-shell run build
npm --prefix apps/website-studio run build
npm --prefix apps/storage test -- --maxWorkers=1
npm --prefix apps/storage run build
npm --prefix apps/app-store run test:content-hash
npm --prefix apps/app-store run build
npm --prefix apps/fitness-coach test -- --maxWorkers=1
npm --prefix apps/fitness-coach run build
python3 scripts/test_suite.py --level fast
python3 scripts/audit_pwa_cache.py
.venv/bin/python scripts/pwa_shell_cache_smoke.py --app-read-models
```

Also run the focused backend tests for all app validator contracts and use the
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

The optional `--app-read-models` smoke creates its own disposable Core repository
and browser profile. Only that child process enables the five second-tranche
app flags. It never accepts a live `--base-url` or changes deployment flags. It
seeds real isolated-frame reads, blocks their display HTTP transport, reloads,
and requires a host-broker warm result before transport recovery. Recorded
metadata contains no app payloads or principal identifiers. This remains
automated Chromium evidence, not PWA-098 physical acceptance.

Populated-model regressions include CRM's structured tag records (not a string
array) and its `results` search envelope, plus consulted Mail bodies and
provider-header changes that must not affect the display revision. The browser
preflight additionally requires a real IndexedDB entry before testing warm paint;
an in-document RAM hit is not accepted as persistence evidence.
