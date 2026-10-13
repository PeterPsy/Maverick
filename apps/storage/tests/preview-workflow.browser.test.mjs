import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createRequire } from 'node:module';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
// Reuse the installed development browser harness; no production dependency.
const requireBrowser = createRequire(join(root, 'apps/browser/package.json'));
const { chromium } = requireBrowser('playwright');
const dist = join(root, 'apps/storage/frontend/dist');
const portrait = '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536"><rect width="1024" height="1536" fill="#bc007c"/></svg>';
const file = {
  id: 'portrait', file_id: 'portrait', path_id: 'portrait', role: 'generated',
  name: 'Portrait image with a long filename.png', extension: '.png', size_bytes: portrait.length,
  relative_path: 'portrait.png', workspace_relative_path: 'storage/generated/portrait.png',
  content_type: 'image/png', preview_kind: 'image', modified_at: '2026-10-13T10:00:00Z', sha256: '',
};
const state = { schema_version: '2', view_mode: 'list', view_filter: {
  mode: 'custom', title: 'Preview fixtures', query: '', role: 'all', kind: 'all',
  file_ids: [file.id], workspace_relative_paths: [], updated_at: '2026-10-13T10:00:00Z',
} };

async function listen(server) {
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  return `http://127.0.0.1:${server.address().port}`;
}

test('mounted portrait preview, fullscreen fallback, native fullscreen, focus and downloads', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'storage-preview-test-'));
  const downloads = [];
  const app = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://fixture');
    if (url.pathname.endsWith('/backend')) {
      let text = '';
      for await (const chunk of request) text += chunk;
      const body = JSON.parse(text);
      const payload = body.action === 'view_filter' || body.action === 'set_view_filter' ? { state }
        : { schema: 'storage.file-catalog.v1', revision: 'f'.repeat(64), state, files: [file], folders: [], available_kinds: ['image'],
            pagination: { offset: 0, limit: 100, total: 1, has_more: false },
            summary: { scope: 'local-roots', containers: [] }, totals: { scope: 'filtered', total_files: 1, total_bytes: file.size_bytes } };
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify(payload));
      return;
    }
    if (url.pathname.endsWith('/media')) {
      const downloading = url.searchParams.get('download') === '1';
      if (downloading) downloads.push(url.searchParams.get('stable_storage_file_id'));
      response.writeHead(200, { 'Content-Type': 'image/svg+xml',
        ...(downloading ? { 'Content-Disposition': `attachment; filename="${file.name}"` } : {}) });
      response.end(portrait);
      return;
    }
    try {
      const path = url.pathname.replace(/^\/apps\/storage\//, '');
      const resource = path.startsWith('assets/') ? path : 'index.html';
      const type = resource.endsWith('.js') ? 'text/javascript' : resource.endsWith('.css') ? 'text/css' : 'text/html';
      response.writeHead(200, { 'Content-Type': type, 'Access-Control-Allow-Origin': '*' });
      let content = await readFile(join(dist, resource));
      if (resource === 'index.html' && url.searchParams.has('test_mobile')) {
        content = content.toString().replace('</head>', '<style>:root{--maverick-shell-mobile-content-top-offset:60px}</style></head>');
      }
      response.end(content);
    } catch { response.writeHead(404); response.end(); }
  });
  const appOrigin = await listen(app);
  const shell = createServer((request, response) => {
    const native = request.url.includes('native');
    const mobile = request.url.includes('mobile');
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end(`<style>body{margin:0}iframe{width:100vw;height:100dvh;border:0}</style>
      <iframe src="${appOrigin}/apps/storage/${mobile ? '?test_mobile=1' : ''}" sandbox="allow-downloads allow-scripts allow-same-origin"
        allow="fullscreen ${native ? '*' : "'none'"}" ${native ? 'allowfullscreen' : ''}></iframe>`);
  });
  const shellOrigin = await listen(shell);
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    for (const scenario of [{ width: 1000, height: 900, native: false }, { width: 1000, height: 900, native: true },
      { width: 390, height: 844, native: false }, { width: 320, height: 568, native: false }]) {
      const page = await browser.newPage({ viewport: scenario, acceptDownloads: true });
      page.setDefaultTimeout(10_000);
      page.on('pageerror', (error) => console.error('Storage fixture error:', error.message));
      await page.goto(`${shellOrigin}/${scenario.width <= 780 ? 'mobile' : scenario.native ? 'native' : 'fallback'}`);
      const frame = page.frameLocator('iframe');
      const opener = frame.getByRole('button', { name: `Open ${file.name}`, exact: true });
      try { await opener.click(); }
      catch (error) {
        console.error('Storage fixture UI:', await page.frames()[1].locator('body').innerText());
        throw error;
      }
      const close = frame.getByRole('button', { name: 'Close preview', exact: true });
      await close.waitFor();
      const image = frame.getByRole('dialog').locator('.preview-modal-body > img');
      await image.waitFor();
      await image.evaluate((element) => element.decode());
      assert.equal(await close.evaluate((element) => document.activeElement === element), true);
      const initialClose = await close.boundingBox();
      assert.ok(initialClose.x >= 0 && initialClose.x + initialClose.width <= scenario.width, 'normal preview controls stay within the viewport');
      if (scenario.width > 780) {
        await frame.getByRole('button', { name: 'Open preview full screen', exact: true }).click();
        await frame.getByRole('button', { name: 'Exit full screen', exact: true }).waitFor();
        await page.waitForTimeout(100);
      }
      const layout = await frame.getByRole('dialog').evaluate((dialog) => {
        const rect = (selector) => dialog.querySelector(selector).getBoundingClientRect().toJSON();
        return { image: rect('.preview-modal-body > img'), body: rect('.preview-modal-body'),
          close: rect('[aria-label="Close preview"]'), viewport: { width: innerWidth, height: innerHeight } };
      });
      assert.ok(layout.image.height <= layout.body.height + 1, 'portrait image stays inside the available height');
      assert.ok(layout.close.top >= 0 && layout.close.bottom <= layout.viewport.height, 'Close stays visible vertically');
      if (scenario.width <= 780) assert.ok(layout.close.top >= 60, 'preview clears the mobile shell header');
      assert.ok(layout.close.right <= layout.viewport.width, 'Close stays visible on narrow screens');
      if (process.env.STORAGE_PREVIEW_SCREENSHOT_DIR) {
        await mkdir(process.env.STORAGE_PREVIEW_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: join(process.env.STORAGE_PREVIEW_SCREENSHOT_DIR, `preview-${scenario.width}-${scenario.native}.png`) });
      }
      const download = frame.getByRole('button', { name: 'Download file', exact: true });
      const downloadEvent = page.waitForEvent('download');
      await download.click();
      const saved = await downloadEvent;
      assert.equal(saved.suggestedFilename(), file.name);
      const target = join(directory, `${scenario.width}-${scenario.native}.png`);
      await saved.saveAs(target);
      assert.equal(await readFile(target, 'utf8'), portrait);
      await close.click();
      await frame.getByRole('dialog').waitFor({ state: 'detached' });
      assert.equal(await opener.evaluate((element) => document.activeElement === element), true);
      await opener.click();
      await close.waitFor();
      if (scenario.width > 780) {
        await frame.getByRole('button', { name: 'Open preview full screen', exact: true }).click();
        await frame.getByRole('button', { name: 'Exit full screen', exact: true }).waitFor();
        await close.press('Escape');
        await frame.getByRole('button', { name: 'Open preview full screen', exact: true }).waitFor();
      }
      await close.press('Escape');
      await frame.getByRole('dialog').waitFor({ state: 'detached' });
      await page.close();
    }
    assert.equal(downloads.length, 4);
  } finally {
    await browser?.close();
    await Promise.all([new Promise((done) => app.close(done)), new Promise((done) => shell.close(done))]);
    await rm(directory, { recursive: true, force: true });
  }
});
