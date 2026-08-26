# PWA Cache Development Baseline — 2026-08-26

This is the M0 development baseline captured before the HTTP/asset and service
worker v2 changes. It is intentionally separate from the physical-device
release gate in `docs/runbooks/pwa_cache_baseline.md`.

## Capture

- probe schema: `maverick.pwa-cache-baseline.v1`;
- engine: system Chromium through Playwright;
- profiles: Desktop Safari and iPhone 15 browser/device emulation;
- samples: five new browser contexts per profile;
- warm reloads: two per context;
- host: temporary local production artifact host with fake test credentials;
- private file probe: not configured;
- content and identifiers captured: none.

Because the engine was Chromium, the two profile labels represent viewport,
user-agent, and input emulation only. These numbers are a repeatable development
signal, not Safari, Home Screen, Mac, or iPhone acceptance evidence.

## Summary

| Profile | Phase | Shell visible p50 / p75 / p95 | Total p50 / p75 / p95 | Requests p50 / p75 / p95 | Transfer bytes p50 / p75 / p95 | SW responses p50 / p75 / p95 |
|---|---|---:|---:|---:|---:|---:|
| Mac/Safari emulation | cold | 492 / 522 / 579 ms | 1243 / 1274 / 1331 ms | 10 / 18 / 18 | 104873 / 105726 / 518212 | 0 / 0 / 0 |
| Mac/Safari emulation | warm | 414 / 614 / 851 ms | 1165 / 1365 / 1602 ms | 18 / 20 / 26 | 107531 / 423059 / 423978 | 1 / 3 / 3 |
| iPhone/Home Screen emulation | cold | 650 / 878 / 1064 ms | 1401 / 1628 / 1815 ms | 10 / 18 / 18 | 99960 / 520658 / 520658 | 0 / 0 / 0 |
| iPhone/Home Screen emulation | warm | 540 / 642 / 1902 ms | 1291 / 1393 / 2653 ms | 20 / 26 / 27 | 104529 / 423059 / 428825 | 0 / 0 / 3 |

Offline reload returned a visible shell in **0/5** controlled runs for each
profile. The browser failed the navigation with
`ERR_INTERNET_DISCONNECTED`, matching the known pre-M2 limitation.

## Interpretation

- warm transfer bytes are highly variable and are not reliably lower than cold
  transfer bytes;
- service-worker participation is inconsistent and does not provide an offline
  navigation fallback;
- no conditional file result exists yet because M1 supplies the validator
  contract and its stable probe target;
- absolute latency budgets remain unset until the required physical Mac/iPhone
  baseline is captured.

The same probe must be repeated after M1 and M2. Expected deltas are zero body
transfer for verified immutable assets, a zero-body `304` for the file probe,
and a visible shell with exactly one Offline indicator after successful M2
precache.
