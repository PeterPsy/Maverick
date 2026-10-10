// Loopback fixture: shipped Base Shell and Connectors, separate frame origin.
import { createServer } from 'node:http';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { fixtureServer } from '../../base-shell/tests/shell-presentation-fixture.mjs';
import { listen, send } from '../../base-shell/tests/browser-contract-support.mjs';

const appRoot = fileURLToPath(new URL('../', import.meta.url));
const dist = resolve(appRoot, 'frontend/dist');
const widgetPath = '/api/apps/widgets/platform-connectors/connectors-sidebar/frontend/';
export const sources = JSON.parse(execFileSync('python3', ['-c',
  'import json,sys;sys.path.insert(0,"backend");from catalog import SOURCES;print(json.dumps(SOURCES))'], { cwd: appRoot, encoding: 'utf8' }));

async function body(request) {
  let bytes = '';
  for await (const chunk of request) bytes += chunk;
  return JSON.parse(bytes || '{}');
}

export async function sidebarFixture() {
  let shellOrigin;
  let prelude;
  const tickets = new Map();
  const catalogRequests = [];
  const shell = fixtureServer([]);
  const fallback = shell.listeners('request')[0];
  shell.removeAllListeners('request');
  const frames = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://localhost');
    if (url.pathname === '/.well-known/maverick-app-frame-session') return send(response, '', 'text/plain', 204);
    if (url.pathname === '/bootstrap') {
      let bytes = '';
      for await (const chunk of request) bytes += chunk;
      const path = tickets.get(new URLSearchParams(bytes).get('ticket'));
      if (!path) return send(response, '', 'text/plain', 403);
      response.writeHead(303, { Location: path }); response.end(); return;
    }
    if (url.pathname === '/api/apps/platform-connectors/backend') {
      const input = await body(request);
      if (input.action === 'sources.list') {
        catalogRequests.push(input.action);
        return send(response, JSON.stringify({ sources }), 'application/json');
      }
      return send(response, JSON.stringify({ sources, connections: [], runs: [], collections: [], media_runtime_available: false }), 'application/json');
    }
    const relative = url.pathname.startsWith(widgetPath)
      ? 'widgets/connectors-sidebar/index.html'
      : url.pathname.replace(/^\/apps\/platform-connectors\//, '') || 'index.html';
    const path = resolve(dist, relative);
    if (!path.startsWith(dist + '/')) return send(response, '', 'text/plain', 404);
    try {
      let content = await readFile(path);
      if (path.endsWith('.html')) {
        content = content.toString().replace('<head>', '<head>' + prelude);
      }
      send(response, content, path.endsWith('.html') ? 'text/html' : path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'image/png');
    } catch { send(response, '', 'text/plain', 404); }
  });
  const frameOrigin = await listen(frames);
  shell.on('request', async (request, response) => {
    const url = new URL(request.url, 'http://localhost');
    const json = (value) => send(response, JSON.stringify(value), 'application/json');
    if (url.pathname === '/api/apps') return json({ items: [{ app_id: 'platform-connectors', name: 'Connectors',
      status: 'enabled', frontend_role: 'workspace', frontend_launchable: true, sidebar_enabled: true,
      frontend_mount: '/apps/platform-connectors/', provides: [], requires: [] }] });
    if (url.pathname === '/api/apps/app-store/backend') return json({ pinned_apps: ['platform-connectors'] });
    if (url.pathname === '/api/apps/dependencies') return json({ workspace_id: 'default', consumer_app_id: 'platform-connectors', status: 'ready', dependencies: [] });
    if (url.pathname === '/api/apps/widgets') return json({ items: url.searchParams.get('content_kind') === 'shell.sidebar.primary'
      ? [{ owner_app_id: 'platform-connectors', widget_id: 'connectors-sidebar', host: 'base-shell',
        content_kinds: ['shell.sidebar.primary'], frontend_mount: widgetPath, actions: { backend: true } }] : [] });
    if (url.pathname === '/api/apps/widgets/context') return json({ context_token: 'fixture-context' });
    if (url.pathname === '/api/app-frames/browser-launch') {
      const input = await body(request);
      const ticket = `fixture-${tickets.size}`;
      tickets.set(ticket, input.path);
      return json({ origin: frameOrigin, bootstrap_url: frameOrigin + '/bootstrap', ticket, ticket_field: 'ticket', method: 'POST' });
    }
    return fallback(request, response);
  });
  shellOrigin = await listen(shell);
  prelude = execFileSync('python3', ['-c', `import json,sys
from types import SimpleNamespace
from core.api.app_frame_browser import _inject_message_relay
b=SimpleNamespace(**json.load(sys.stdin))
html=_inject_message_relay(b'<head></head>',b).decode()
print(html.removeprefix('<head>').removesuffix('</head>'))`], {
    cwd: resolve(appRoot, '../..'), encoding: 'utf8',
    input: JSON.stringify({ platform_origin: shellOrigin, parent_origin: shellOrigin, mount_app_id: 'platform-connectors',
      app_id: 'platform-connectors', workspace_id: 'default', widget_id: '' }),
  });
  return { shell, frames, origin: shellOrigin, catalogRequests };
}
