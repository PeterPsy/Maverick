# PWA cache M2R implementation validation — 2026-08-31

## Status

The M2R source, generated artifacts, contracts, automated tests, and shared
backend activation are implemented and verified. The physical Safari/Home
Screen matrix remains an explicit external release gate and is not represented
as passed in this record.

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
  flags, generated artifacts, and negative routing tests;
- `02b8a206` — deferred reads retain their own loading state and pending
  controllers are cancelled across reload/scope changes;
- `85288833` — current probes, runbooks, security text, and this M2R evidence
  replace the superseded acceptance model without rewriting M2 history;
- `c40fe500` — the remaining hosting test fixture uses manifest v2;
- `5e489388`, `1e8b6027` — authorization revalidation is terminal and the
  mounted-frame preservation assertion is explicit.

## Built artifact

The reviewed Base Shell build has id
`bd942620ec5380adf200623b970137dd741ac87562eb7204bbf940712f488a07`
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
| Base Shell frontend | 28 files, 127 tests passed |
| Worker/build harness | 13 tests passed |
| Frontend manifest loader | 10 tests passed |
| PWA feature flags | 4 tests passed |
| Public PWA config API | 2 tests passed |
| Root-shell PWA asset host | focused slow test passed |

The complete API unit directory subsequently passed **305 tests**. The default
fast repository suite was also executed. Its M2R-related manifest fixture
failures were corrected and re-run green; the aggregate remains non-green for
unrelated existing repository-budget, legacy cross-app fixture, and Senses
provider-selection failures outside this change. Those failures are not
reclassified as M2R evidence.

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

The deferred shared-backend activation was completed after the active runtime
sessions stopped:

1. `maverick-core.service` restarted successfully and has been active since
   `2026-08-31T13:19:49Z`;
2. `/health` returned `status: ok` and `/api/pwa/config` matched
   `maverick.pwa-config.v2` exactly, including generation `v2` and both
   cache-centric feature flags disabled;
3. `maverick app base-shell frontend build --json` completed with status
   `built`, build id
   `bd942620ec5380adf200623b970137dd741ac87562eb7204bbf940712f488a07`,
   three immutable assets, fourteen revalidated assets, and a published
   `maverick.app.frontend-changed` event;
4. `scripts/pwa_shell_cache_smoke.mjs` passed against
   `http://127.0.0.1:8014` in Chromium at `2026-08-31T13:21:18.022Z`.

The smoke result used schema `maverick.pwa-shell-cache-smoke.v2` and passed the
online install, mounted-tree preservation, standard-shell restart without
network, non-shell navigation bypass, excluded dynamic requests, transparent
transport recovery, and absence of superseded mode UI. This closes the shared
backend activation gate; it does not replace the physical-device release gate
below.

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
