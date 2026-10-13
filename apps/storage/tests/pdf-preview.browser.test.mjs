import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createRequire } from 'node:module';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const { chromium } = createRequire(join(root, 'apps/browser/package.json'))('playwright');
const dist = join(root, 'apps/storage/frontend/dist');

// A real two-page PDF with different colours makes page changes observable.
function fixturePdf() {
  const stream = (colour) => `q ${colour} rg 0 0 300 400 re f Q\n`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> /Contents 5 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> /Contents 6 0 R >>',
    ...['0.8 0 0.4', '0 0.3 0.8'].map((colour) => `<< /Length ${stream(colour).length} >>\nstream\n${stream(colour)}endstream`),
  ];
  let content = '%PDF-1.4\n';
  const offsets = objects.map((object, index) => {
    const offset = content.length;
    content += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = content.length;
  content += `xref\n0 7\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}`;
  return Buffer.from(`${content}trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
}

const pdf = fixturePdf();
const files = ['Report.pdf', 'Broken.pdf'].map((name, index) => ({
  id: `pdf-${index}`, file_id: `pdf-${index}`, path_id: `pdf-${index}`, role: 'generated',
  name, extension: '.pdf', size_bytes: pdf.length, relative_path: name,
  workspace_relative_path: `storage/generated/${name}`, content_type: 'application/pdf',
  preview_kind: 'pdf', modified_at: '2026-10-13T10:00:00Z', sha256: '',
}));
const state = { schema_version: '2', view_mode: 'list', view_filter: {
  mode: 'custom', title: 'PDF fixtures', query: '', role: 'all', kind: 'all',
  file_ids: files.map((file) => file.id), workspace_relative_paths: [], updated_at: '2026-10-13T10:00:00Z',
} };

async function listen(server) {
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  return `http://127.0.0.1:${server.address().port}`;
}

test('PDFs render in isolated Storage and embedded widgets on desktop and mobile', async () => {
  let workerLoads = 0;
  let mediaLoads = 0;
  const assets = createServer(async (request, response) => {
    try {
      const resource = new URL(request.url, 'http://fixture').pathname.replace(/^\/apps\/storage\//, '');
      const content = await readFile(join(dist, resource));
      if (resource.includes('pdf.worker')) workerLoads++;
      response.writeHead(200, { 'Content-Type': resource.endsWith('.css') ? 'text/css' : 'text/javascript',
        'Access-Control-Allow-Origin': '*' });
      response.end(content);
    } catch { response.writeHead(404); response.end(); }
  });
  const assetOrigin = await listen(assets);
  const app = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://fixture');
    if (url.pathname.startsWith('/api/apps/widgets/context/')) {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ context: { content: { payload: { file_id: files[0].id } } } }));
      return;
    }
    if (url.pathname.endsWith('/backend')) {
      let body = '';
      for await (const chunk of request) body += chunk;
      const action = JSON.parse(body).action;
      const payload = action === 'file_info' ? { file: files[0] }
        : action === 'view_filter' || action === 'set_view_filter' ? { state }
          : { schema: 'storage.file-catalog.v1', revision: 'f'.repeat(64), state, files, folders: [], available_kinds: ['pdf'],
            pagination: { offset: 0, limit: 100, total: 2, has_more: false },
            summary: { scope: 'local-roots', containers: [] }, totals: { scope: 'filtered', total_files: 2, total_bytes: pdf.length * 2 } };
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify(payload));
      return;
    }
    if (url.pathname.endsWith('/media')) {
      if (!request.headers.cookie?.includes('pdf_fixture=1')) { response.writeHead(403); response.end(); return; }
      mediaLoads++;
      response.writeHead(200, { 'Content-Type': 'application/pdf' });
      response.end(url.searchParams.get('stable_storage_file_id') === files[1].id ? Buffer.from('invalid PDF') : pdf);
      return;
    }
    try {
      const widget = url.pathname.includes('/widgets/');
      let html = (await readFile(join(dist, widget ? 'widgets/file-preview/index.html' : 'index.html'), 'utf8'))
        .replaceAll('/apps/storage/', `${assetOrigin}/apps/storage/`);
      response.writeHead(200, { 'Content-Type': 'text/html', 'Set-Cookie': 'pdf_fixture=1; HttpOnly; SameSite=Lax; Path=/',
        'Content-Security-Policy': "object-src 'none'; base-uri 'self'" });
      response.end(html);
    } catch { response.writeHead(404); response.end(); }
  });
  const appOrigin = await listen(app);
  const shell = createServer((request, response) => {
    const widget = request.url.includes('widget');
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end(`<style>body{margin:0;background:#202024}iframe{width:100vw;height:100dvh;border:0}</style>
      <iframe src="${appOrigin}${widget ? '/api/apps/widgets/storage/file-preview/frontend/#context=fixture' : '/apps/storage/'}"
        sandbox="allow-downloads allow-scripts allow-same-origin" allow="fullscreen *"></iframe>`);
  });
  const shellOrigin = await listen(shell);
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    for (const widget of [false, true]) for (const width of [1000, 320]) {
      const page = await browser.newPage({ viewport: { width, height: 844 } });
      page.setDefaultTimeout(10_000);
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(`${shellOrigin}/${widget ? 'widget' : 'storage'}`);
      const frame = page.frameLocator('iframe');
      if (!widget) await frame.getByRole('button', { name: `Open ${files[0].name}`, exact: true }).click();
      const viewer = frame.getByRole('region', { name: `PDF preview for ${files[0].name}`, exact: true });
      const canvas = viewer.getByRole('img', { name: 'PDF page 1', exact: true });
      await canvas.waitFor();
      const colour = async (label) => viewer.getByRole('img', { name: label, exact: true }).evaluate((element) =>
        [...element.getContext('2d').getImageData(20, 20, 1, 1).data]);
      assert.deepEqual(await colour('PDF page 1'), [204, 0, 102, 255]);
      assert.equal(await viewer.getByLabel('PDF page', { exact: true }).getAttribute('max'), '2');
      const initialWidth = await canvas.evaluate((element) => element.width);
      await viewer.getByRole('button', { name: 'Zoom in', exact: true }).click();
      await canvas.waitFor();
      assert.ok(await canvas.evaluate((element) => element.width) > initialWidth);
      await viewer.getByRole('button', { name: 'Fit PDF to width', exact: true }).click();
      await canvas.waitFor();
      await viewer.getByRole('button', { name: 'Next page', exact: true }).click();
      await viewer.getByRole('img', { name: 'PDF page 2', exact: true }).waitFor();
      assert.deepEqual(await colour('PDF page 2'), [0, 76, 204, 255]);
      assert.equal(await viewer.getByRole('button', { name: 'Next page', exact: true }).isDisabled(), true);
      const bounds = await viewer.getByRole('toolbar').boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1, 'PDF controls fit the viewport');
      if (process.env.STORAGE_PREVIEW_SCREENSHOT_DIR) {
        await mkdir(process.env.STORAGE_PREVIEW_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: join(process.env.STORAGE_PREVIEW_SCREENSHOT_DIR, `pdf-${widget ? 'widget' : 'storage'}-${width}.png`) });
      }
      if (!widget) {
        await frame.getByRole('button', { name: 'Close preview', exact: true }).click();
        await frame.getByRole('button', { name: `Open ${files[1].name}`, exact: true }).click();
        await frame.getByRole('alert').waitFor();
        assert.match(await frame.getByRole('alert').innerText(), /PDF/i);
        await frame.getByRole('button', { name: 'Close preview', exact: true }).click();
        await frame.getByRole('button', { name: `Open ${files[0].name}`, exact: true }).click();
        await frame.getByRole('img', { name: 'PDF page 1', exact: true }).waitFor();
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
    assert.ok(workerLoads >= 4, 'the PDF worker loads from the public asset origin');
    assert.ok(mediaLoads >= 4, 'PDF bytes load through the authenticated Storage media route');
  } finally {
    await browser?.close();
    await Promise.all([assets, app, shell].map((server) => new Promise((done) => server.close(done))));
  }
});
