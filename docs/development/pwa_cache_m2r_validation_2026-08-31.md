# PWA cache M2R implementation validation — 2026-08-31

## Status

The M2R source, generated artifacts, contracts, and automated tests are
implemented. Deployment activation on the shared backend and the physical
Safari/Home Screen matrix remain explicit external release gates; they are not
represented as passed in this record.

This record supersedes the product conclusions, not the historical facts, in
`pwa_cache_m2_validation_2026-08-26.md`.

## Reviewed checkpoints

The implementation chain reviewed here includes:

- `a5cf0f65` — ADR-0012 supersedes the old product mode;
- `5852d392` — canonical architecture adopts transparent cache boundaries;
- `c4e6c51c`, `f38d895e`, `0a5c23d3` — product contract and policy v2;
- `05f02b9a` — dedicated connectivity UI and alternative document removed;
- `037296e4`, `4994e45b` — transport recovery renamed and bootstrap retry kept
  internal to normal loading;
- `8aec9e99` — manifest/config v2, standard-shell worker fallback, cache-centric
  flags, generated artifacts, and negative routing tests.

## Built artifact

The reviewed Base Shell build has id
`d5dfb5a22eadcc114cb3a5c30d2b3fc28b56391ae3903338e52bc159a878f452`
and contains:

- schema `maverick.frontend-assets.v2`;
- one normal HTML entrypoint, `index.html`;
- `navigation_fallback: "index.html"` selected at URL `/`;
- three Rollup-verified immutable bundles;
- fourteen revalidated public artifacts, including the generated worker;
- sixteen URL/path/SHA-256/size precache records;
- no alternative document and no unresolved generation token.

`load_frontend_asset_manifest(..., verify_files=True)` accepted all six tracked
v2 frontend manifests and every declared byte in their current artifacts.

## Automated evidence

| Surface | Result |
|---|---|
| Base Shell frontend | 28 files, 126 tests passed |
| Worker/build harness | 13 tests passed |
| Frontend manifest loader | 10 tests passed |
| PWA feature flags | 4 tests passed |
| Public PWA config API | 2 tests passed |
| Root-shell PWA asset host | focused slow test passed |

The worker harness verifies:

- atomic candidate installation and preservation of the active build;
- normal `index.html` reuse only for `/`, `/app`, and `/app/*`;
- no generated HTML when the verified fallback is absent;
- no fallback for other navigations;
- bypass of API, SSE, WebSocket, backend, sidecar, worker, and range traffic;
- digest repair, non-destructive recovery, best-effort writes, bounded cache
  ownership, waiting-worker coordination, and selective kill-switch cleanup.

The component/API tests verify that transport failures retain normal loading,
`429/502/503/504` read retries remain bounded, browser events are only retry
hints, another successful Maverick response can wake pending work, mounted
shell state remains rendered during revalidation, and `403` is terminal.

## Rollout configuration

The public projection is `maverick.pwa-config.v2` and exposes only:

- `service_worker.enabled` with generation `v2`;
- `features.data_cache`;
- `features.storage_file_cache`.

The removed file-cache name and mutation-outbox flag have no runtime alias.
Malformed values remain fail-closed.

## Deployment activation note

The official `maverick app base-shell frontend build --json` invocation ran the
new build but the already-running shared backend still had the v1 loader in
memory and therefore rejected publication of the refresh event. Restarting that
service at the time of this review would also terminate active agent/runtime
children in its systemd control group, so it was deliberately not used as a
development shortcut. After the shared sessions finish, an operator must:

1. restart `maverick-core.service` through the normal service procedure;
2. verify `/health` and schema `maverick.pwa-config.v2`;
3. rerun `maverick app base-shell frontend build --json`;
4. run `scripts/pwa_shell_cache_smoke.mjs` against the active endpoint.

This operational deferral does not change the committed artifact, but the live
shared endpoint is not claimed as M2R-certified until those steps pass.

## Physical-device matrix

| Container | Status |
|---|---|
| Minimum supported Safari on macOS | pending physical execution |
| Current Safari on supported macOS | pending physical execution |
| macOS Dock-installed web app | pending physical execution |
| Minimum supported Safari on iOS/iPadOS | pending physical execution |
| Current Safari on supported iPhone | pending physical execution |
| iPhone Home Screen web app | pending physical execution |

Each row must use the exact reviewed build and record only device model,
OS/browser version, build id, UTC timestamp, and pass/fail. The release reviewer
must follow `docs/runbooks/pwa_shell_v2.md`; emulation cannot close this gate.
