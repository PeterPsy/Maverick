// Isolated test-only frontend host; API responses are intercepted by Playwright.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';

const root = resolve('frontend/dist');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, 'http://localhost');
    const name = url.pathname.includes('/assets/') ? url.pathname.slice(url.pathname.indexOf('/assets/') + 1) : 'index.html';
    const path = resolve(root, name);
    if (!path.startsWith(root + sep)) throw new Error('invalid path');
    response.setHeader('Content-Type', mime[extname(path)] || 'application/octet-stream');
    response.end(await readFile(path));
  } catch { response.writeHead(404); response.end(); }
});
server.listen(4178, '127.0.0.1');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)));
