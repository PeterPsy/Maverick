# Startup Performance Instrumentation

Date: 2026-07-08

Maverick startup optimization uses opt-in instrumentation so normal local runs
do not emit extra performance logs.

## Core Logs

Set `MAVERICK_STARTUP_PERF_LOGS=1` before starting the ASGI host to emit
structured `startup.performance` records through the `maverick.startup` logger.

Current server-side timings cover:

- app frontend asset serving;
- REST runtime thread catalog payload construction;
- runtime thread WebSocket snapshot construction, including encoded snapshot
  byte size when instrumentation is enabled.

These logs are intended for baseline and regression checks. They do not change
HTTP or WebSocket response contracts.

## Browser Markers

The base shell records startup markers in `window.__maverickStartupMetrics`.
Set `localStorage["maverick.startupMetrics"] = "1"` or append
`?startup_metrics=1` to mirror those entries to `console.debug`.

Current browser markers cover:

- shell session fetch;
- shell blocking bootstrap payloads;
- total shell bootstrap duration;
- widget discovery;
- widget context creation.

## Asset Baseline

Run:

```bash
python3 scripts/startup_performance_baseline.py
python3 scripts/startup_performance_baseline.py --json
```

The script reports raw and gzip sizes for committed `base-shell` and `chat`
frontend `dist` assets. Use it before and after compression and code-splitting
work so bundle changes stay comparable.

## Browser Baseline

Run against an existing authenticated host:

```bash
MAVERICK_STARTUP_USERNAME=<username> MAVERICK_STARTUP_PASSWORD=<password> \
  python3 scripts/startup_browser_baseline.py --base-url http://127.0.0.1:8014 --json
```

For local repeatable test runs, the script can start a temporary core host with
insecure test credentials:

```bash
python3 scripts/startup_browser_baseline.py --use-insecure-test-defaults --json
```

The browser baseline measures desktop and mobile cold page loads for `/app/chat`:
shell visible time, Chat iframe loaded time, composer ready time, HTTP request
count, WebSocket count, time to first WebSocket, first
`runtime.thread.snapshot` time/bytes/thread count, iframe count, widget iframe
count, and external request count.

When credentials or the local Playwright browser executable are not available,
the script returns a JSON payload with `skipped: true` and a concrete reason so
CI and manual runs can distinguish environment gaps from regressions.
