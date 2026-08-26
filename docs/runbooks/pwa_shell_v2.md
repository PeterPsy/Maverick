# Base Shell Service Worker v2 Operations And Acceptance

This runbook operates and validates the M2 public offline shell. It does not
authorize private app read models, offline files, prompts, mutations, agents,
models, tools, or an outbox.

## Owned artifacts and caches

- Build manifest: `apps/base-shell/frontend/dist/maverick-frontend-assets.json`
- Worker source: `apps/base-shell/frontend/public/sw.js`
- Generated worker: `apps/base-shell/frontend/dist/sw.js`
- Localized fallback: `apps/base-shell/frontend/dist/offline.html`
- Versioned shell cache: `maverick-static-v2:<build_id>`
- Visited verified app assets: `maverick-app-static-v2`
- Exact migratable legacy cache: `maverick-base-shell-v3`

No operation in this runbook may clear the entire origin. IndexedDB, OPFS, and
unrelated Cache API names are out of scope.

## Build and automated preflight

```bash
npm --prefix apps/base-shell run build
npm --prefix apps/base-shell test
npm --prefix apps/base-shell run test:service-worker
python3 -m unittest tests.unit.apps.test_frontend_assets
MAVERICK_TEST_LEVEL=slow python3 -m unittest \
  apps/base-shell/tests/test_builtin_apps.py \
  -k test_platform_host_serves_root_shell_pwa_assets_without_session
```

Verify all built bytes against the generated manifest:

```bash
python3 - <<'PY'
from pathlib import Path
from core.apps.frontend_assets import load_frontend_asset_manifest

manifest = load_frontend_asset_manifest(
    Path("apps/base-shell/frontend/dist"),
    required=True,
    verify_files=True,
)
assert manifest.offline_path == "offline.html"
assert {record.url for record in manifest.precache} >= {"/", "/offline.html"}
print(manifest.build_id, len(manifest.precache))
PY
```

Against a production-artifact host, run the full-restart browser probe:

```bash
node scripts/pwa_shell_offline_smoke.mjs \
  --base-url http://127.0.0.1:8014 \
  --engine chromium
```

`--engine webkit` is useful only when the Playwright WebKit binary is present;
it remains emulation and does not satisfy the physical Safari gate.

## Update and interrupted-install drill

1. Open build A in two tabs and confirm both are controlled by `/sw.js`.
2. Deploy build B. A worker-only change must also produce a different
   `build_id` and cache name.
3. Block one B precache request. Confirm B's install fails, its incomplete
   cache disappears, build A remains active, and both tabs still work.
4. Restore the request and trigger `registration.update()` or reload online.
5. Confirm the single sidebar status says **Aggiornamento disponibile** and B
   remains waiting; it must not call `skipWaiting` on its own.
6. Select **Aggiorna** in local-content management. Confirm all tabs already
   controlled by the M2 client reload on `controllerchange` and use B.
7. Confirm activation removed only obsolete `maverick-static-v2:*` and the
   exact legacy cache. The app-static runtime cache, an intentionally created
   unrelated Cache API entry, IndexedDB, and OPFS must remain.

## Corruption and recovery drill

1. While online, delete or replace one response in the active versioned shell
   cache through DevTools.
2. Request that immutable asset. The worker must reject the bad bytes, fetch
   and verify the declared SHA-256/size, and repair the entry.
3. Delete `/offline.html`, go offline, and select **Verifica cache**. Recovery
   must fail visibly without deleting other verified entries.
4. Reconnect and repeat. The dialog must report **Cache della shell
   verificata** and every generated precache record must be present.

## Kill switch and rollback

Set the backend process environment and restart that process if required:

```bash
MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2=off
```

Confirm `/api/pwa/config` returns schema `maverick.pwa-config.v1`, generation
`v2`, and `service_worker.enabled: false`. On the next online shell load the
client must unregister the root Maverick worker and delete only:

- `maverick-static-v2:*`;
- `maverick-app-static-v2`;
- `maverick-base-shell-v3`.

An unreachable config endpoint does **not** imply a kill switch: the client
keeps the functioning worker so an offline launch cannot unregister itself.
Re-enable the flag, reload online, and confirm a fresh verified cache installs.

## Physical Safari and installed-PWA release gate

Automated Chromium/WebKit and Lighthouse results are development evidence only.
Before releasing M2, execute every row below against the same reviewed build.
Safari and installed apps are independent containers; clear only the container
under test before its first run.

| Container | First online + precache | Fully terminate, then cold offline reopen | One indicator / no iframe or remote action | Confirmed reconnect | Update / interrupted install / recovery / kill switch | Evidence |
|---|---|---|---|---|---|---|
| Safari 17.4 on macOS 14.4 (minimum floor) | pending | pending | pending | pending | pending | pending |
| Current Safari on supported macOS | pending | pending | pending | pending | pending | pending |
| macOS Dock-installed web app | pending | pending | pending | pending | pending | pending |
| Safari 17.4 on iOS/iPadOS 17.4 (minimum floor) | pending | pending | pending | pending | pending | pending |
| Current Safari on supported iPhone | pending | pending | pending | pending | pending | pending |
| iPhone Home Screen web app | pending | pending | pending | pending | pending | pending |

For each row record device model, OS/browser version, build id, UTC timestamp,
and pass/fail only. Do not record workspace, user, content, file, cookie, URL
token, or app-record identifiers. A release reviewer must reject a row if:

- the cold offline reopen fails after a successful precache;
- the current-app icon is not replaced in the same sidebar slot in expanded
  and rail layouts, or a second global indicator appears;
- the icon returns before a fresh Maverick response succeeds;
- an iframe, prompt, mutation, model, agent, tool, backend, sidecar, API, SSE,
  or WebSocket path appears usable from the offline shell;
- an interrupted update harms the prior worker/cache; or
- activation, recovery, or rollback removes IndexedDB, OPFS, runtime app
  assets during ordinary activation, or an unrelated Cache API entry.

Also open the build once in Safari private browsing. Treat denied or ephemeral
storage as a supported server-first degradation, not as durable offline
availability; the shell must not crash or claim persistence.
