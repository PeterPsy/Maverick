import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
export const chromium = createRequire(join(root, 'apps/browser/package.json'))('playwright').chromium;
const dist = join(root, 'apps/storage/frontend/dist');
const svg = (width, height) => `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#bc007c"/></svg>`;

function pdf() {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  for (let page = 1; page <= 2; page++) {
    const stream = `BT /F1 18 Tf 40 720 Td (Preview page ${page}) Tj ET`;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${objects.length + 2} 0 R >>`,
      `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  }
  let text = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(text.length); text += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const start = text.length;
  text += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  text += offsets.slice(1).map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  return text + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`;
}

const specifications = [
  ['portrait', 'Portrait image with a long filename.png', 'image', svg(1024, 6000), 'image/svg+xml'],
  ['small', 'Small.png', 'image', svg(64, 64), 'image/svg+xml'],
  ['pdf', 'Report.pdf', 'pdf', pdf(), 'application/pdf'],
  ['text', 'Long.txt', 'text', ('A'.repeat(500) + '\n').repeat(300), 'text/plain'],
];
export const fixtures = specifications.map(([id, name, kind, content, mime]) => ({
  content, mime, file: { id, file_id: id, path_id: id, role: 'generated', name,
    extension: name.slice(name.lastIndexOf('.')), size_bytes: Buffer.byteLength(content),
    relative_path: name, workspace_relative_path: `storage/generated/${name}`,
    content_type: mime, preview_kind: kind, modified_at: '2026-10-14T07:00:00Z', sha256: '' },
}));
export const portrait = fixtures[0].content;
export const file = fixtures[0].file;

async function listen(server) {
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  return `http://127.0.0.1:${server.address().port}`;
}

export async function startPreviewFixture() {
  const downloads = [];
  const files = fixtures.map((item) => item.file);
  const state = { schema_version: '2', view_mode: 'list', view_filter: { mode: 'custom', title: 'Preview fixtures',
    query: '', role: 'all', kind: 'all', file_ids: files.map((item) => item.id), workspace_relative_paths: [], updated_at: 'fixture' } };
  const app = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://fixture');
    const json = (value) => { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(value)); };
    if (url.pathname.includes('/widgets/context/')) {
      const selected = fixtures.find((item) => url.pathname.endsWith(item.file.id)) || fixtures[0];
      json({ context: { content: { payload: { file: selected.file } } } }); return;
    }
    if (url.pathname.endsWith('/backend')) {
      let text = ''; for await (const chunk of request) text += chunk;
      const body = JSON.parse(text);
      const selected = fixtures.find((item) => item.file.id === body.file_id || item.file.id === body.stable_storage_file_id
        || item.file.relative_path === body.relative_path || item.file.workspace_relative_path === body.workspace_relative_path) || fixtures[0];
      if (body.action === 'view_filter' || body.action === 'set_view_filter') { json({ state }); return; }
      if (body.action === 'file_info') { json({ file: selected.file }); return; }
      if (body.action === 'read_file') {
        json({ file: selected.file, content_type: selected.mime, content_base64: Buffer.from(selected.content).toString('base64') }); return;
      }
      json({ schema: 'storage.file-catalog.v1', revision: 'f'.repeat(64), state, files, folders: [],
        available_kinds: ['image', 'pdf', 'text'], pagination: { offset: 0, limit: 100, total: files.length, has_more: false },
        summary: { scope: 'local-roots', containers: [] }, totals: { scope: 'filtered', total_files: files.length, total_bytes: 1000 } });
      return;
    }
    if (url.pathname.endsWith('/media')) {
      const selected = fixtures.find((item) => item.file.id === url.searchParams.get('stable_storage_file_id')) || fixtures[0];
      const downloading = url.searchParams.get('download') === '1';
      if (downloading) downloads.push(selected.file.id);
      response.writeHead(200, { 'Content-Type': selected.mime,
        ...(downloading ? { 'Content-Disposition': `attachment; filename="${selected.file.name}"` } : {}) });
      response.end(selected.content); return;
    }
    try {
      const resource = url.pathname.replace(/^\/apps\/storage\//, '');
      const path = resource.startsWith('assets/') || resource.startsWith('widgets/') ? resource : 'index.html';
      const type = path.endsWith('.js') || path.endsWith('.mjs') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html';
      let content = await readFile(join(dist, path));
      if (path === 'index.html' && url.searchParams.has('test_mobile')) {
        content = content.toString().replace('</head>', '<style>:root{--maverick-shell-mobile-content-top-offset:60px}</style></head>');
      }
      response.writeHead(200, { 'Content-Type': type, 'Access-Control-Allow-Origin': '*' }); response.end(content);
    } catch { response.writeHead(404); response.end(); }
  });
  const appOrigin = await listen(app);
  const shell = createServer((request, response) => {
    const native = request.url.includes('native');
    const url = new URL(request.url, 'http://fixture');
    const widget = url.searchParams.get('widget');
    const src = widget ? `/apps/storage/widgets/file-preview/index.html?context=${widget}`
      : `/apps/storage/${request.url.includes('mobile') ? '?test_mobile=1' : ''}`;
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end(`<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}iframe{width:100vw;height:${widget ? '320px' : '100dvh'};border:0}</style>
      <iframe src="${appOrigin}${src}" sandbox="allow-downloads allow-scripts allow-same-origin"
        allow="fullscreen ${native ? '*' : "'none'"}" ${native ? 'allowfullscreen' : ''}></iframe>`);
  });
  return { shellOrigin: await listen(shell), downloads, close: () => Promise.all([
    new Promise((done) => app.close(done)), new Promise((done) => shell.close(done)),
  ]) };
}
