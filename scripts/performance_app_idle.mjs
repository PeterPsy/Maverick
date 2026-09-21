/** Twenty real frontend surfaces; supporting roles are promoted only by the fixture. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { baseUrl, chromium, executablePath } from './performance_browser_support.mjs';

const headless = process.env.MAVERICK_PERFORMANCE_HEADFUL !== '1';
const phaseDuration = Number(process.env.MAVERICK_PERFORMANCE_IDLE_PHASE_MS || 5_000);
assert(Number.isInteger(phaseDuration) && phaseDuration >= 5_000 && phaseDuration <= 60_000);
// Playwright's normal contexts force focus emulation, hiding real tab suspension.
// Own a disposable browser/profile and attach without changing native visibility.
async function launchNativeBrowser() {
  const binary = executablePath();
  assert(binary, 'A local Chromium executable is required.');
  const profile = mkdtempSync(join(tmpdir(), 'maverick-idle-browser-'));
  const child = spawn(binary, ['--remote-debugging-port=0', '--no-sandbox', '--no-first-run',
    '--no-default-browser-check', `--user-data-dir=${profile}`, '--window-size=1440,1000',
    ...(headless ? ['--headless=new'] : []), 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  const exited = new Promise(resolve => child.once('exit', resolve));
  let browser;
  async function close() {
    await browser?.close().catch(() => {});
    let timer;
    if (child.pid && child.exitCode === null && child.signalCode === null) {
      child.kill('SIGTERM');
      try { await Promise.race([exited, new Promise(resolve => { timer = setTimeout(resolve, 5_000); })]); }
      finally { clearTimeout(timer); }
      if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await exited; }
    }
    rmSync(profile, { recursive: true, force: true });
  }
  try {
    const endpoint = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => fail(new Error('Native browser startup timed out')), 30_000);
      const fail = error => { clearTimeout(timer); reject(error); };
      let output = '';
      child.once('error', fail);
      child.once('exit', () => fail(new Error('Native browser exited before CDP was available')));
      child.stderr.on('data', chunk => {
        output = (output + chunk).slice(-4096);
        const match = /DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[^\s]+)/.exec(output);
        if (match) { clearTimeout(timer); resolve(match[1]); }
      });
    });
    browser = await chromium.connectOverCDP(endpoint, { noDefaults: true });
    return { browser, close };
  } catch (error) { await close(); throw error; }
}
const native = await launchNativeBrowser();
const { browser } = native;
const context = browser.contexts()[0];
const page = context.pages()[0];
await page.setViewportSize({ width: 1440, height: 1000 });
context.setDefaultTimeout(30_000);
const cdp = await browser.newBrowserCDPSession();
const requests = [], errors = [], sockets = new Set(), connections = [];
const appIdForUrl = url => /\/apps\/([^/]+)/.exec(url)?.[1] || 'shell';
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => {
  if (!request.url().includes('/api/')) return;
  let body;
  try { body = request.postDataJSON(); } catch { /* Non-JSON transport. */ }
  requests.push({ time: Date.now(), owner: appIdForUrl(request.frame().url()),
    path: new URL(request.url()).pathname, action: body?.action });
});
page.on('websocket', socket => {
  sockets.add(socket);
  connections.push({ time: Date.now(), path: new URL(socket.url()).pathname });
  socket.on('close', () => sockets.delete(socket));
});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const activeFrame = async () => {
  const element = page.locator('iframe.bs-workspace-app-frame.is-active');
  await element.waitFor({ state: 'visible' });
  return (await element.elementHandle()).contentFrame();
};
async function openApp(appId) {
  for (let attempt = 0; attempt < 3 && new URL(page.url()).pathname !== `/app/${appId}`; attempt++) {
    const previous = await activeFrame();
    try {
      await previous.evaluate(appId => window.parent.postMessage({ type: 'maverick.app.open-app', app_id: appId },
        window.__MAVERICK_PLATFORM_ORIGIN__), appId);
      break;
    } catch (error) {
      // A successful app switch can replace the sender while evaluate is still
      // settling. Retry only that known navigation race from the new active frame.
      if (!(error instanceof Error) || !error.message.includes('Execution context was destroyed')) throw error;
      await sleep(50);
    }
  }
  await page.waitForURL(url => url.pathname === `/app/${appId}`);
  let frame = await activeFrame();
  const deadline = Date.now() + 30_000;
  while (appIdForUrl(frame.url()) !== appId && Date.now() < deadline) {
    await sleep(50);
    frame = await activeFrame();
  }
  await frame.waitForLoadState('domcontentloaded');
  assert.equal(appIdForUrl(frame.url()), appId);
  return frame;
}
const phases = [];
async function measure(label, duration = phaseDuration) {
  const before = (await cdp.send('SystemInfo.getProcessInfo')).processInfo;
  const start = Date.now();
  await sleep(duration);
  const after = (await cdp.send('SystemInfo.getProcessInfo')).processInfo;
  const cpu = after.reduce((total, entry) => total + Math.max(0, entry.cpuTime - (before.find(old => old.id === entry.id)?.cpuTime || 0)), 0);
  phases.push({ label, elapsed_ms: Date.now() - start, browser_cpu_ms: cpu * 1000,
    requests: requests.filter(read => read.time >= start), connections: connections.filter(read => read.time >= start),
    document_hidden: await page.evaluate(() => document.hidden),
    frames: await page.locator('iframe.bs-workspace-app-frame').evaluateAll(elements => elements.map(element => ({
      title: element.title, active: element.classList.contains('is-active'), src: element.src.split(/[?#]/)[0],
    }))), sockets: [...sockets].map(socket => new URL(socket.url()).pathname) });
}
try {
  assert((await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: 'fixture-admin', password: 'fixture-only-password' },
  })).ok());
  const registry = await (await context.request.get(`${baseUrl}/api/apps`)).json();
  const appIds = ['agents', 'app-store', 'calendar', 'chat', 'checklist', 'crm', 'design-studio', 'developer-kit',
    'docs-studio', 'document-generator', 'dynamic-views', 'fitness-coach', 'mail', 'memory', 'senses',
    'settings', 'skills', 'storage', 'vault', 'website-studio'];
  const opened = [];
  await page.goto(`${baseUrl}/app/storage`, { waitUntil: 'domcontentloaded' });
  await activeFrame();
  for (const id of appIds) {
    const frame = await openApp(id);
    await sleep(800);
    opened.push({ app_id: id, frame_url: frame.url().split(/[?#]/)[0],
      initial_text: (await frame.locator('body').innerText()).slice(0, 350) });
    process.stderr.write(`Opened ${opened.length}/20: ${id}\n`);
  }
  await openApp('storage');
  await sleep(2_000);
  await measure('twenty-open-storage-active');
  await page.setViewportSize({ width: 600, height: 900 });
  const close = page.getByRole('button', { name: 'Chiudi sidebar', exact: true });
  if (await close.isVisible()) await close.click();
  await sleep(1_100);
  await measure('sidebar-closed');
  await context.setOffline(true);
  await sleep(1_100);
  await measure('offline');
  await context.setOffline(false);
  await sleep(1_100);
  await measure('online-resumed');
  const background = await context.newPage();
  await background.goto('about:blank');
  await background.bringToFront();
  await page.waitForFunction(() => document.hidden);
  await sleep(1_100);
  await measure('second-tab-foreground');
  await background.close();
  await page.bringToFront();
  await page.waitForFunction(() => !document.hidden);
  await sleep(1_100);
  await measure('foreground-resumed');
  console.log(JSON.stringify({ schema: 1, boundary: 'authenticated-disposable-chromium', browser: browser.version(),
    headless, phase_duration_ms: phaseDuration, native_tab_visibility: true,
    promoted_supporting_frontends: ['developer-kit', 'document-generator'], opened,
    resumable_apps: registry.items.filter(app => app.frontend_resumable).map(app => app.app_id),
    phases, errors, physical_device_gate: 'not-tested' }, null, 2));
} finally {
  await native.close();
}
