# PWA cache M2 validation — 2026-08-26

> **Historical and superseded.** This file records what was actually validated
> for the original M2 checkpoint. Its alternative document, indicator, dialog,
> iframe-unmounting, and action-blocking expectations are not current product
> requirements. ADR-0012 and
> `docs/development/pwa_cache_m2r_validation_2026-08-31.md` are normative for
> the corrected M2R gate. The historical facts below have not been rewritten.

This checkpoint records implementation and repeatable development evidence for
the Base Shell offline container and service worker v2. It does not claim the
physical Safari/Home Screen release gate, which remains explicitly pending in
`docs/runbooks/pwa_shell_v2.md`.

## Built artifact

The Base Shell production build emitted:

- two HTML entrypoints: `index.html` and localized `offline.html`;
- three Rollup-verified immutable bundles;
- fifteen revalidated public artifacts, including the generated worker;
- seventeen URL/path/SHA-256/size precache records;
- no unresolved `__MAVERICK_*` generation token.

`core.apps.frontend_assets.load_frontend_asset_manifest(...,
verify_files=True)` re-read every declared artifact and accepted the manifest.
The build id is recorded by the smoke output rather than treated as a stable
source constant; any shell, worker-template, asset, or precache-selection
change intentionally replaces it.

The reviewed artifact used for the final controlled matrix had build id
`2c12864f3b1122c82fa56b2b1c5fb61befa18da352766ac1785bcf9decc93640`.

## Automated acceptance matrix

| Required M2 behavior | Evidence |
|---|---|
| First online install, full browser termination/restart, then offline | Persistent-profile Chromium smoke passed against a temporary real `PlatformHost` |
| Interrupted candidate update preserves prior build | Node worker harness interrupts precache and verifies the candidate cache is removed while the previous cache remains |
| Incompatible old tab | Candidate waits behind an active worker; only the explicit protocol calls `skipWaiting`; every already-controlled M2 tab reloads on controller change |
| Corrupt or missing cache | Digest mismatch repair and non-destructive failed recovery tests pass |
| Kill switch | Worker and browser-client tests unregister and remove only the three known static namespace classes |
| API/SSE/backend/sidecar never intercepted | Worker routing unit test and live offline browser fetch failures pass; WebSocket, worker, range, non-GET, cross-origin are excluded in routing |
| Expanded and rail indicator | Component tests render exactly one indicator in the current-app slot for each mode |
| No duplicate and restore only after confirmation | Rail replacement/restoration test plus delayed reconnect-probe test pass |
| Prompt and other online-only actions blocked | Offline render contains no iframe or prompt action in component and persistent-browser tests |
| Safari and Home Screen real | **Pending external physical-device release gate; not represented as passed** |

Five independent Chromium persistent profiles reported `first_online_install`,
`full_browser_restart_offline`, `excluded_dynamic_requests`, and
`confirmed_reconnect` as passed: **5/5 controlled runs**. Every run verified
all seventeen generated precache entries were present in the build-specific
cache. The same automated probe reported WebKit as skipped because no
Playwright WebKit executable was installed; even a passing run would remain
non-physical evidence.

## Safety boundaries observed

- M2 stores only public shell/static bytes and a non-sensitive last-success
  timestamp; it stores no private app payload.
- Offline rendering unmounts app frames and provides the local-content dialog
  without making models, agents, tools, prompts, or mutations actionable.
- `activate` never enumerates or deletes IndexedDB or OPFS and retains the
  visited-app static runtime cache.
- Recovery repairs in place. A failed fetch cannot delete already verified
  active-shell entries.
- The kill switch fails safely when config is unreachable and never clears the
  whole origin.

The five-run controlled matrix used a temporary `PlatformHost` on a separate
loopback port so it could not disturb other agents. After the shared backend
was restarted successfully, the same persistent-profile smoke also passed
against its active `127.0.0.1:8014` endpoint with the identical build id and
seventeen precache records.
