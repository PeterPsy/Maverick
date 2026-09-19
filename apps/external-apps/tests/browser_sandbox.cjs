// Foreground-only real-browser proof for public, stateless Vite-style documents.
const { chromium } = require('playwright');
const http = require('node:http');
const assert = require('node:assert/strict');
const headers = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));

(async () => {
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push(request.url);
    Object.entries(headers).forEach(([name, value]) => response.setHeader(name, value));
    response.setHeader('Content-Type', request.url.endsWith('.js') ? 'text/javascript' : 'text/html');
    response.end(request.url === '/module.js'
      ? `import('./lazy.js').then(() => document.body.dataset.ready = 'yes');`
      : request.url === '/lazy.js' ? `window.lazyLoaded = true;`
      : '<!doctype html><h1>Public fixture</h1><script type="module" src="/module.js"></script>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(() => document.body.dataset.ready === 'yes');
    const result = await page.evaluate(async () => {
      const state = { origin: window.origin, lazy: window.lazyLoaded };
      for (const [name, action] of Object.entries({
        cookie: () => document.cookie = 'maverick_session=attacker; Domain=127.0.0.1; Path=/',
        storage: () => localStorage.setItem('private', 'data'),
        domain: () => document.domain = '127.0.0.1',
        routing: () => history.pushState({}, '', '/deep/link'),
      })) {
        try { action(); state[name] = 'allowed'; } catch (error) { state[name] = error.name; }
      }
      try { await fetch('/api/private'); state.fetch = 'allowed'; } catch { state.fetch = 'blocked'; }
      return state;
    });
    assert.deepEqual(result, { origin: 'null', lazy: true, cookie: 'SecurityError',
      storage: 'SecurityError', domain: 'SecurityError', routing: 'allowed', fetch: 'blocked' });
    assert.equal(requests.includes('/api/private'), false);
    assert.deepEqual(await page.context().cookies(), []);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
