import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { build } from "vite";
import { browserExecutable, close, listen, runBrowser, send } from "./browser-contract-support.mjs";

test("metrics survive real document reload only as history and prune expired localStorage shards", async (context) => {
  const browser = browserExecutable();
  if (!browser) { context.skip("Chromium or Chrome is required for the metrics browser contract."); return; }
  const bundle = await build({
    configFile: false, logLevel: "silent",
    build: {
      write: false, minify: false,
      lib: { entry: resolve(import.meta.dirname, "../../../packages/pwa-cache/src/metrics.ts"), formats: ["es"] },
    },
  });
  const module = (Array.isArray(bundle) ? bundle[0] : bundle).output.find((output) => output.type === "chunk").code;
  const profile = mkdtempSync(resolve(tmpdir(), "maverick-metrics-browser-"));
  context.after(() => rmSync(profile, { recursive: true, force: true }));
  const server = createServer((request, response) => {
    send(response, request.url === "/metrics.js" ? module : documentSource,
      request.url === "/metrics.js" ? "text/javascript" : "text/html");
  });
  try {
    const origin = await listen(server);
    const result = await runBrowser(browser, [
      "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
      `--user-data-dir=${profile}`, "--virtual-time-budget=5000", "--dump-dom", origin,
    ]);
    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /data-result="pass"/u, result.stdout);
  } finally { await close(server); }
});

const documentSource = `<!doctype html><html><body data-result="pending"><script type="module">
import { createPwaCacheMetricsCollector } from '/metrics.js';
try {
  if (!sessionStorage.getItem('reloaded')) {
    for (let index = 0; index < 50; index++) {
      const collector = createPwaCacheMetricsCollector({ now: () => 1000 });
      collector.recordDataCache({ kind: 'hit' });
      if (index === 0) collector.recordRetry({ attempt: 0, keyHash: 'live', kind: 'wait_started', waitMs: 100 });
    }
    localStorage.setItem('unrelated', 'preserve');
    sessionStorage.setItem('reloaded', '1');
    location.reload();
  } else {
    const collector = createPwaCacheMetricsCollector({ now: () => 1100 });
    const restored = collector.snapshot();
    if (restored.requestWait.pendingCount !== 0 || restored.requestWait.oldestPendingMs !== null
        || restored.counters.pwa_request_wait_started !== 1 || restored.counters.pwa_data_cache_hit !== 50) throw Error('reload');
    collector.recordRetry({ attempt: 0, keyHash: 'current', kind: 'wait_started', waitMs: 100 });
    if (collector.snapshot().requestWait.pendingCount !== 1) throw Error('live');
    createPwaCacheMetricsCollector({ now: () => 8 * 24 * 60 * 60 * 1000 });
    if (Object.keys(localStorage).some((key) => key.startsWith('maverick.pwa-cache.metrics.v1:writer:'))) throw Error('retention');
    if (localStorage.getItem('unrelated') !== 'preserve') throw Error('ownership');
    document.body.dataset.result = 'pass';
  }
} catch (error) { document.body.dataset.result = 'fail'; document.body.dataset.error = error.message; }
</script></body></html>`;
