/** Browser-level warm paint with real isolated app frames and host persistence.
 * Only used with disposable test-host flags; captures closed transport metadata. */
export async function exerciseAppReadModels(context, baseUrl) {
  await context.addInitScript(() => {
    window.__pwaDisplayTrace = [];
    const original = MessagePort.prototype.postMessage;
    MessagePort.prototype.postMessage = function (data, ...rest) {
      if (['maverick.pwa.data-cache.result.v1', 'maverick.pwa.data-cache.network-request.v1'].includes(data?.type)) {
        window.__pwaDisplayTrace.push({ type: data.type, app: data.app_id, conditional: Boolean(data.known_revision), phase: data.phase, status: data.status, source: data.source, error_name: data.error?.name, error_status: data.error?.status });
      }
      return original.call(this, data, ...rest);
    };
  });
  const page = await context.newPage();
  const results = [];
  const http = [];
  page.on('response', async (response) => {
    const path = new URL(response.url()).pathname;
    if (!/^\/api\/apps\/[a-z-]+\/backend$/.test(path)) return;
    let body; try { body = response.request().postDataJSON(); } catch { return; }
    if (body?.action !== 'pwa.read_model') return;
    const data = await response.json().catch(() => ({}));
    http.push({ app: path.split('/')[3], status: response.status(), error: typeof data.error === 'string' ? data.error : undefined });
  });
  try {
    for (const app of ['calendar', 'chat', 'crm', 'mail', 'fitness-coach']) {
      await page.goto(`${baseUrl}/app/${app}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction((app) => window.__pwaDisplayTrace?.some((item) => item.app === app && item.phase === 'initial' && item.status === 'ok'), app, { timeout: 45000 });
      const stored = await page.evaluate(async () => {
        const request = indexedDB.open('maverick-pwa-data-v1');
        const database = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = reject; });
        const rows = database.transaction('entries').objectStore('entries').getAll();
        const entries = await new Promise((resolve, reject) => { rows.onsuccess = () => resolve(rows.result); rows.onerror = reject; });
        database.close();
        return entries.reduce((counts, row) => { counts[row.appId] = (counts[row.appId] || 0) + 1; return counts; }, {});
      });
      http.push({ app, stored_entry_counts: stored });
      if (!(stored[app] > 0)) throw new Error(`${app}: cold read did not seed IndexedDB`);
      const holdRead = async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        let body = {};
        try { body = request.postDataJSON() || {}; } catch { /* GET */ }
        const displayRead = url.searchParams.get('projection') === 'display'
          || (url.pathname === `/api/apps/${app}/backend` && ['pwa.read_model', 'app.bootstrap'].includes(body.action));
        if (displayRead) await route.abort('internetdisconnected');
        else await route.continue();
      };
      await context.route('**/api/**', holdRead);
      try {
        await page.goto(`${baseUrl}/app/${app}`, { waitUntil: 'domcontentloaded' });
        await page.waitForFunction((app) => window.__pwaDisplayTrace?.some((item) => item.app === app && item.phase === 'initial' && item.status === 'ok' && item.source === 'cache'), app, { timeout: 20000 });
        const visible = await page.locator('iframe.is-active').count();
        if (!visible) throw new Error(`${app}: warm display did not mount an active frame`);
        results.push({ app, indexeddb_seed_verified: true, scoped_warm_paint_with_display_transport_blocked: 'passed' });
      } finally {
        await context.unroute('**/api/**', holdRead);
      }
    }
  } catch (error) {
    const mounted = await page.locator('iframe').evaluateAll((frames) => frames.map((frame) => ({ title: frame.title, active: frame.classList.contains('is-active') })));
    const trace = await page.evaluate(() => window.__pwaDisplayTrace).catch(() => []);
    throw new Error(`App display smoke failed: ${error.message}; transport metadata=${JSON.stringify(trace)}; HTTP=${JSON.stringify(http)}; frames=${JSON.stringify(mounted)}`);
  } finally {
    await page.close();
  }
  return results;
}
