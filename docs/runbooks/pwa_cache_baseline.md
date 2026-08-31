# PWA Cache Baseline And Device Acceptance

This runbook captures redaction-safe cache and transport-resilience evidence.
The original M0 measurements remain historical; M2R acceptance verifies that
cache reuse never creates a separate product mode or changes the normal UI tree.
Store raw results outside source control unless they are explicitly reviewed and
redacted.

## Automated development capture

Start a production-build Maverick host, then run:

```bash
node scripts/pwa_cache_baseline.mjs \
  --base-url http://127.0.0.1:8014 \
  --username "$MAVERICK_STARTUP_USERNAME" \
  --password "$MAVERICK_STARTUP_PASSWORD" \
  --engine webkit \
  --runs 5 \
  --warm-reloads 2 \
  --output /tmp/maverick-pwa-baseline.json
```

To measure conditional file reads, add an authenticated same-origin stable
Storage media URL with `--file-url`. The output records only status codes, ETag
presence, and body sizes; it never records the URL or file identity.

When Playwright WebKit is unavailable, the probe emits a structured `skipped`
result. Chromium is useful during development with `--engine chromium`, but it
does not satisfy the physical WebKit release gate.

Schema `maverick.pwa-cache-baseline.v2` records:

- shell-visible and total navigation time;
- request/response counts and estimated response transfer bytes;
- API, immutable, `304`, and service-worker response counts;
- cold and warm p50/p75/p95 summaries;
- first file status/body size and conditional status/body size;
- a transport-loss reopen with standard-shell, loading, iframe, and legacy-mode
  marker counts.

Passwords, cookies, response bodies, file names, signed/capability URLs,
workspace ids, user ids, message text, and app record ids are excluded.

## Persistent-profile shell probe

Run the cache/lifecycle probe independently of the performance capture:

```bash
node scripts/pwa_shell_cache_smoke.mjs \
  --base-url http://127.0.0.1:8014 \
  --engine chromium \
  --username "$MAVERICK_STARTUP_USERNAME" \
  --password "$MAVERICK_STARTUP_PASSWORD"
```

Credentials are optional as a pair. Supplying fake development credentials also
proves that an already-mounted app iframe is not removed when transport is lost.
The probe verifies manifest v2, complete precache, standard-shell reuse,
network-only navigation bypass, dynamic-request bypass, normal bootstrap loading,
transparent recovery, and absence of the superseded mode UI. Playwright remains
development evidence rather than a physical-device gate.

## Physical-device release capture

Before releasing M2R and each later persistence milestone, repeat the matrix on:

1. minimum supported Safari on macOS;
2. current Safari on macOS;
3. the same host installed as a Dock web app;
4. minimum supported Safari on iPhone/iPadOS;
5. current Safari on iPhone;
6. the same host installed as a Home Screen web app;
7. Chrome or Edge desktop as a cross-platform control;
8. private browsing as a safe-degradation check.

For each container record only device model, OS/browser version, build id, UTC
timestamp, and pass/fail for each scenario. Do not record account or content
identifiers. Safari and an installed PWA are distinct storage containers.

Run at least five samples of:

1. first online open after clearing only that container;
2. second online open;
3. slow network;
4. intermittent backend reachability;
5. transport loss after a warm open;
6. full browser/PWA termination and reopen after a successful precache;
7. transport recovery after a server-side change;
8. revoked session (`401`/`403` must be terminal, not loading forever);
9. quota pressure or denied persistence;
10. browser-evicted site data;
11. interrupted worker update and recovery;
12. server-side kill switch.

For lifecycle, integrity, recovery, and rollback details, also follow
`docs/runbooks/pwa_shell_v2.md`.

## Gates

- M0 values are historical and do not define absolute latency thresholds.
- Physical results establish separate Mac and iPhone p75/p95 budgets.
- M1 file revalidation requires `304` with a zero-byte response body.
- M1 immutable assets require zero body transfer on a warm open.
- M2R requires the same standard shell and mounted tree during transport loss,
  normal loading for a cache miss, no dedicated connectivity UI or copy, and no
  intercepted API/SSE/WebSocket/backend/sidecar/range request.
- A first visit with no verified cache retains normal browser failure semantics.
- A skipped probe, emulated phone, Lighthouse result, or screenshot alone does
  not satisfy physical-device acceptance.

## Failure triage

Preserve only redaction-safe diagnostics:

- manifest schema/build id and asset path category, never private URLs;
- service-worker lifecycle state and owned cache names;
- status code, cache policy, ETag presence, and byte counts;
- feature availability, quota estimate, and persistence boolean;
- safe categories such as `install_failed`, `cache_corrupt`,
  `quota_exceeded`, `transport_unavailable`, or `retry_cancelled`.

If rollback is required, disable `MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2`,
verify schema `maverick.pwa-config.v2` at `/api/pwa/config`, reload with working
transport, and confirm that the client unregisters the worker and removes only
known Maverick static caches.
