/** Authenticated cold/warm Shell navigation until real Storage rows are painted. */
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { baseUrl, chromium, executablePath } from './performance_browser_support.mjs';

const browser = await chromium.launch({ headless: true, executablePath: executablePath() });
const results = [];
const trials = Number(process.env.MAVERICK_PERFORMANCE_STARTUP_TRIALS || 5);
const compactEvidence = process.env.MAVERICK_PERFORMANCE_COMPACT === '1';
assert(Number.isInteger(trials) && trials >= 1 && trials <= 5);
const percentile = (values, fraction) => {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
};
const statistics = values => ({ min: Math.min(...values), median: percentile(values, 0.5),
  p95: percentile(values, 0.95), max: Math.max(...values) });
try {
  for (let trial = 0; trial < trials; trial++) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    context.setDefaultTimeout(30_000);
    try {
      await context.addInitScript(() => {
        window.__MAVERICK_PERFORMANCE_STORAGE_PAINTS__ = [];
        window.addEventListener('message', event => {
          const payload = event.data;
          if (!payload || typeof payload !== 'object') return;
          if (payload.type === 'maverick.performance.storage-painted') {
            window.__MAVERICK_PERFORMANCE_STORAGE_PAINTS__.push(payload);
            return;
          }
          if (payload.type !== 'maverick.app.navigate' || (payload.app_id && payload.app_id !== 'storage')) return;
          const started = Number(payload.params?.performance_probe_started_epoch_ms);
          const token = payload.params?.performance_probe_token;
          if (!Number.isFinite(started) || typeof token !== 'string') return;
          const deadline = Date.now() + 30_000;
          const waitForContent = () => {
            if (!document.querySelector('.animated-file-item:not(.storage-file-skeleton)')) {
              if (Date.now() < deadline) requestAnimationFrame(waitForContent);
              return;
            }
            requestAnimationFrame(() => requestAnimationFrame(() => window.parent.postMessage({
              type: 'maverick.performance.storage-painted', token, duration_ms: Date.now() - started,
            }, '*')));
          };
          requestAnimationFrame(waitForContent);
        }, true);
      });
      assert((await context.request.post(`${baseUrl}/api/auth/login`, {
        data: { username: 'fixture-admin', password: 'fixture-only-password' },
      })).ok());
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const requests = new Map();
      const sizes = new Set();
      page.on('request', request => {
        let action;
        try { action = request.postDataJSON()?.action; } catch { /* Non-JSON requests. */ }
        requests.set(request, { path: new URL(request.url()).pathname.replace(/(\/widgets\/context\/).+/, '$1<context>'),
          action, resource_type: request.resourceType(), started: performance.now(), complete: false, size: null });
      });
      page.on('requestfinished', request => {
        const record = requests.get(request);
        if (!record) return;
        record.complete = true;
        record.finished = performance.now();
        const pending = request.sizes().then(size => { record.size = size; }).catch(() => {}).finally(() => sizes.delete(pending));
        sizes.add(pending);
      });
      page.on('requestfailed', request => {
        const record = requests.get(request);
        if (!record) return;
        record.complete = true;
        record.finished = performance.now();
      });
      const waitForNetworkQuiescence = async () => {
        const deadline = performance.now() + 30_000;
        let quietSince = null;
        while (performance.now() < deadline) {
          const busy = [...requests.values()].some(record => !record.complete && record.resource_type !== 'websocket');
          if (busy) quietSince = null;
          else if (quietSince === null) quietSince = performance.now();
          else if (performance.now() - quietSince >= 250) return;
          await new Promise(resolve => setTimeout(resolve, 25));
        }
        throw new Error('Network did not become quiescent before warm-navigation measurement.');
      };
      for (let visit = 0; visit < 6; visit++) {
        if (visit > 0) {
          await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
          await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
          const current = page.locator('iframe.bs-workspace-app-frame.is-active');
          await current.waitFor();
          const frame = await (await current.elementHandle()).contentFrame();
          await frame.evaluate(() => window.parent.postMessage({ type: 'maverick.app.open-app', app_id: 'checklist' },
            window.__MAVERICK_PLATFORM_ORIGIN__));
          await page.waitForURL(url => url.pathname === '/app/checklist');
          await page.locator('iframe.bs-workspace-app-frame.is-active[title="Checklist viewport"]').waitFor();
          // A warm-navigation sample starts from a settled shell. Initial app
          // bootstrap and floating-chat prewarm are separate cold-start work.
          await waitForNetworkQuiescence();
        }
        const rtt = [];
        for (let index = 0; index < 5; index++) {
          const started = performance.now();
          assert((await context.request.get(`${baseUrl}/health`)).ok());
          rtt.push(performance.now() - started);
        }
        const started = performance.now();
        const milestones = {};
        if (visit === 0) {
          await page.goto(`${baseUrl}/app/storage?role=generated&folder_relative_path=reading`, { waitUntil: 'domcontentloaded' });
        } else {
          const checklistElement = page.locator('iframe.bs-workspace-app-frame.is-active[title="Checklist viewport"]');
          const checklist = await (await checklistElement.elementHandle()).contentFrame();
          const token = `${trial}-${visit}`;
          await checklist.evaluate(token => window.parent.postMessage({ type: 'maverick.app.open-app', app_id: 'storage',
            params: { role: 'generated', folder_relative_path: 'reading', performance_probe_token: token,
              performance_probe_started_epoch_ms: String(Date.now()) } }, window.__MAVERICK_PLATFORM_ORIGIN__), token);
          await page.waitForURL(url => url.pathname === '/app/storage');
          await page.waitForFunction(token => window.__MAVERICK_PERFORMANCE_STORAGE_PAINTS__
            ?.some(item => item.token === token), token);
          milestones.browser_paint_ms = await page.evaluate(token => window.__MAVERICK_PERFORMANCE_STORAGE_PAINTS__
            .find(item => item.token === token).duration_ms, token);
        }
        milestones.url_ready_ms = performance.now() - started;
        const iframe = page.locator('iframe.bs-workspace-app-frame.is-active[title="Storage viewport"]');
        await iframe.waitFor();
        milestones.frame_visible_ms = performance.now() - started;
        const storage = await (await iframe.elementHandle()).contentFrame();
        milestones.frame_resolved_ms = performance.now() - started;
        await storage.locator('.animated-file-item:not(.storage-file-skeleton)').first().waitFor();
        milestones.first_row_ms = performance.now() - started;
        await storage.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const useful = performance.now();
        const beforeUseful = [...requests.values()].filter(record => record.started >= started && record.started <= useful);
        const completed = beforeUseful.filter(record => record.complete && record.finished <= useful);
        const inflight = beforeUseful.filter(record => !record.complete || record.finished > useful).map(record => record.path);
        await Promise.allSettled([...sizes]);
        const bytes = completed.reduce((total, record) => total
          + Math.max(0, record.size?.responseBodySize || 0) + Math.max(0, record.size?.responseHeadersSize || 0), 0);
        results.push({ trial, visit, kind: visit ? 'warm-in-shell-navigation' : 'cold-authenticated-navigation',
          useful_content_ms: useful - started, health_rtt_ms: rtt,
          milestones,
          response_transfer_bytes_completed_at_useful: bytes, requests_completed_at_useful: completed.length,
          missing_transfer_sizes: completed.filter(record => !record.size).length, inflight_at_useful: inflight,
          network: beforeUseful.map(record => ({ path: record.path, action: record.action, started_ms: record.started - started,
            finished_ms: record.finished ? record.finished - started : null, size: record.size })),
          rendered_files: await storage.locator('.animated-file-item:not(.storage-file-skeleton)').count(),
          service_worker_controlled: await page.evaluate(() => Boolean(navigator.serviceWorker.controller)), errors: [...errors] });
        assert.deepEqual(errors, []);
        process.stderr.write(`Startup trial ${trial + 1}/5 visit ${visit}: ${(useful - started).toFixed(1)} ms\n`);
      }
    } finally { await context.close(); }
  }
  const cold = results.filter(result => result.kind === 'cold-authenticated-navigation');
  const warm = results.filter(result => result.kind === 'warm-in-shell-navigation');
  const warmRttQualified = warm.filter(result => Math.max(...result.health_rtt_ms) <= 30);
  const warmPaint = statistics(warm.map(result => result.milestones.browser_paint_ms));
  const warmRttQualifiedPaint = warmRttQualified.length
    ? statistics(warmRttQualified.map(result => result.milestones.browser_paint_ms))
    : null;
  const summary = {
    cold_useful_content_ms: statistics(cold.map(result => result.useful_content_ms)),
    warm_useful_content_ms: statistics(warm.map(result => result.useful_content_ms)),
    warm_browser_paint_ms: warmPaint,
    warm_rtt_qualified_browser_paint_ms: warmRttQualifiedPaint,
    warm_rtt_qualified_samples: warmRttQualified.length,
    health_rtt_ms: statistics(results.flatMap(result => result.health_rtt_ms)),
    warm_target_under_300_ms: Boolean(warmRttQualifiedPaint && warmRttQualifiedPaint.p95 <= 300),
    warm_rendered_files_min: Math.min(...warm.map(result => result.rendered_files)),
  };
  const evidenceResults = compactEvidence ? results.map(({ network: _network, ...result }) => result) : results;
  console.log(JSON.stringify({ schema: 1, boundary: 'authenticated-disposable-chromium', browser: browser.version(),
    workload: '350 files; five cold Shell navigations and 25 warm in-shell returns after first real Storage row, plus two animation frames',
    login_included: false, cold_contexts: trials, warm_in_shell_navigations: trials * 5,
    diagnostic: trials !== 5, compact_evidence: compactEvidence, summary, results: evidenceResults,
    physical_device_gate: 'not-tested' }, null, 2));
} finally { await browser.close(); }
