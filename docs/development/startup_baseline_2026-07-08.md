# Maverick Startup Baseline

Date: 2026-07-08

Source plan: `storage/generated/maverick-startup-performance-plan.md`
(`file_21acd1af772e4e2db7213b7a0d9b41db`), read through the Storage app.

## Asset Baseline

Collected with `python3 scripts/startup_performance_baseline.py` against the
committed frontend `dist` artifacts before PR1 behavior changes.

| App | Raw bytes | Gzip bytes | Files |
| --- | ---: | ---: | ---: |
| `base-shell` | 371,506 | 104,704 | 3 |
| `chat` | 1,226,193 | 343,820 | 20 |

Largest startup-relevant assets:

| Asset | Raw bytes | Gzip bytes |
| --- | ---: | ---: |
| `apps/chat/frontend/dist/assets/main-BmKSFigP.js` | 667,403 | 207,664 |
| `apps/base-shell/frontend/dist/assets/index-DnH92o3N.js` | 298,709 | 91,720 |
| `apps/chat/frontend/dist/assets/main-DofQDBOg.css` | 199,451 | 30,001 |
| `apps/chat/frontend/dist/assets/shellTheme-DSHsNWwB.js` | 198,622 | 62,159 |
| `apps/base-shell/frontend/dist/assets/index-DCD0xWKF.css` | 69,842 | 12,039 |

HTML baseline:

| App | HTML bytes | Expected cache policy |
| --- | ---: | --- |
| `base-shell` | 2,145 | `no-store` |
| `chat` | 1,926 | `no-store` |

## Local HTTP Baseline

Measured with a temporary uvicorn server on `127.0.0.1` and no authenticated
browser session. The local admin password was not available through a non-secret
environment value, so authenticated browser trace metrics are deferred to a run
with operator-provided credentials.

| Path | Code | TTFB seconds | Total seconds | Bytes |
| --- | ---: | ---: | ---: | ---: |
| `/` | 200 | 0.045234 | 0.055893 | 2,145 |
| `/health` | 200 | 0.004043 | 0.004100 | 50 |
| `/api/session` | 200 | 0.034394 | 0.042411 | 28 |
| `/api/apps` | 401 | 0.029015 | 0.029485 | 40 |
| `/api/status` | 401 | 0.021277 | 0.042215 | 40 |
| `/api/settings/platform` | 401 | 0.001335 | 0.001632 | 40 |
| `/apps/chat/assets/main-BmKSFigP.js` | 200 | 0.067720 | 0.068564 | 667,403 |
| `/apps/base-shell/assets/index-DnH92o3N.js` | 200 | 0.079973 | 0.080493 | 298,709 |

## Static Code Baseline

Before PR1/PR2:

- `FloatingChatHost` mounts `WidgetSlot` even when Chat is already active; this
  can trigger widget discovery/context work while the host is visually hidden.
- Shell bootstrap waits for session, app list, `/api/status`, workspaces,
  `/api/settings/platform`, and pinned apps before clearing the primary loading
  state.
- Runtime thread WebSocket snapshots and `_threads_payload` REST responses
  build full workspace thread catalogs.
- Main Chat, sidebar, footer, and dock have independent runtime thread stream
  entry points.

## Target Thresholds From Plan

- Hidden floating `WidgetSlot` mount with Chat active: `0` after PR1a.
- Thread streams per tab/shell with Chat active: `1` after PR2.
- Initial thread snapshot: `<= 50` threads or `<= 100 KB` JSON after PR2,
  subject to recalibration with authenticated traces.
- Compressible JS/CSS transfer reduction: at least `40%` after PR3 if assets
  are currently uncompressed.

## PR1a Measurement

After shell bootstrap/widget gate changes, `python3 scripts/startup_performance_baseline.py`
reported:

| App | Raw bytes | Gzip bytes | Files |
| --- | ---: | ---: | ---: |
| `base-shell` | 374,321 | 105,848 | 4 |
| `chat` | 1,226,193 | 343,820 | 20 |

The authenticated shell entry asset changed from
`apps/base-shell/frontend/dist/assets/index-u8gEaTu7.js` at 300,044 raw bytes
and 92,104 gzip bytes to
`apps/base-shell/frontend/dist/assets/index-B68RkT9S.js` at 276,437 raw bytes
and 84,768 gzip bytes. The login shader now lives in
`LoginPaperBackground-DhP0-1ON.js` at 25,087 raw bytes and 8,096 gzip bytes,
so authenticated refreshes no longer pay that code in the initial shell chunk.

## PR1b Measurement

After decoupling initial Chat readiness from the agent catalog and noncritical
capability probes, `python3 scripts/startup_performance_baseline.py` reported:

| App | Raw bytes | Gzip bytes | Files |
| --- | ---: | ---: | ---: |
| `base-shell` | 374,321 | 105,848 | 4 |
| `chat` | 1,227,854 | 344,289 | 20 |

The main Chat JS asset changed to
`apps/chat/frontend/dist/assets/main-BCFBFO6-.js` at 668,954 raw bytes and
208,141 gzip bytes. The composer can now become interactive after the
conversation target and core dependencies resolve, while the agent catalog
continues loading in the background.

## PR1c Measurement

After splitting provider setup from runtime-session inventory,
`python3 scripts/startup_performance_baseline.py` reported:

| App | Raw bytes | Gzip bytes | Files |
| --- | ---: | ---: | ---: |
| `base-shell` | 374,327 | 105,847 | 4 |
| `chat` | 1,227,854 | 344,289 | 20 |

The base-shell authenticated entry asset changed to
`apps/base-shell/frontend/dist/assets/index-C0Qec5qD.js` at 276,443 raw bytes
and 84,768 gzip bytes. Initial provider setup now uses
`/api/settings/provider-setup`; cleanup-scope runtime inventory is loaded from
`/api/settings/runtime-sessions` by the Settings app instead of the shell
bootstrap path.
