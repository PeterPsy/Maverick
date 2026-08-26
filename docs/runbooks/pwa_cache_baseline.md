# PWA Cache Baseline And Device Acceptance

This runbook captures the M0 baseline and the evidence required at each PWA
milestone. Store results outside source control unless they are explicitly
redacted review evidence.

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

To measure the conditional file path, add an authenticated, same-origin stable
Storage media URL with `--file-url`. The output records only whether a file
probe was configured, status codes, ETag presence, and body sizes; it never
records the URL or file identity.

When Playwright WebKit is not installed, the probe emits a structured `skipped`
result. Chromium may be used during development with `--engine chromium`, but
it does not satisfy the WebKit release gate.

The probe records:

- shell-visible and total navigation time;
- request and response counts;
- estimated response transfer bytes;
- API, immutable, `304`, and service-worker response counts;
- cold and warm p50/p75/p95 summaries;
- first file status/body size and conditional status/body size;
- whether an offline reload returned a visible shell and one Offline indicator.

Passwords, cookies, response bodies, file names, signed/capability URLs,
workspace ids, user ids, message text, and app record ids are excluded.

## Physical-device release capture

Playwright emulation is not physical-device evidence. Before releasing M2 and
each later persistence milestone, repeat the matrix on:

1. one supported Mac running current Safari;
2. the same host installed as a Dock web app;
3. one supported iPhone running current Safari;
4. the same host installed as a Home Screen web app.

Record browser/OS version, device model, build id, network profile, run count,
request count, transferred bytes, shell-visible time, useful-content time,
file status/body bytes, and offline outcome. Do not record account or content
identifiers.

For each container run at least five samples of:

1. first online open after clearing only that container;
2. second online open;
3. slow network;
4. intermittent backend reachability;
5. offline reload after a successful warm open;
6. full browser/PWA termination and cold offline reopen;
7. reconnect after a server-side change;
8. revoked session;
9. quota pressure or denied persistence;
10. browser-evicted site data.

Safari and an installed PWA are separate containers and must have separate
rows. An iPhone and Mac are separate devices and do not share cache evidence.

## Gates

- M0 establishes values; it does not invent absolute latency thresholds.
- After the physical baseline, record separate Mac and iPhone p75/p95 budgets.
- M1 file revalidation requires `304` with a zero-byte response body.
- M1 immutable assets require zero body transfer on a warm open.
- M2 requires a visible offline shell in every controlled run after successful
  precache, exactly one global Offline indicator, and no intercepted API/SSE.
- A skipped probe, emulated iPhone, Lighthouse result, or screenshot alone does
  not satisfy physical-device acceptance.

## Failure triage

Preserve only redaction-safe diagnostics:

- manifest schema/build id and asset path category, never private URLs;
- service-worker lifecycle state and owned cache names;
- status code, cache policy, ETag presence, and byte counts;
- feature availability, quota estimate, and persistence boolean;
- safe error category such as `install_failed`, `cache_corrupt`,
  `quota_exceeded`, or `backend_unreachable`.

If rollback is required, disable `MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2`,
verify `/api/pwa/config`, reload online, and confirm that the client unregisters
the worker and removes only known Maverick static caches.
