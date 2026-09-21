/** Browser contracts for real local streams and deterministic Drive responses. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { baseUrl, chromium, executablePath } from './performance_browser_support.mjs';

const browser = await chromium.launch({ headless: true, executablePath: executablePath() });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
await context.addInitScript(() => {
  const messages = [];
  Object.defineProperty(window, '__MAVERICK_PERFORMANCE_MESSAGES__', { value: messages });
  window.addEventListener('message', event => {
    const payload = event.data && typeof event.data === 'object' ? event.data : {};
    messages.push({ type: payload.type, app_id: payload.app_id,
      param_keys: payload.params && typeof payload.params === 'object' ? Object.keys(payload.params).sort() : [] });
    if (messages.length > 20) messages.shift();
  });
});
context.setDefaultTimeout(20_000);
const page = await context.newPage();
const errors = [];
const reads = [];
const media = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => {
  if (request.url().includes('/media')) media.push({ url: request.url(), method: request.method() });
});
let storage;
const navigate = async params => storage.evaluate(params => window.parent.postMessage({
  type: 'maverick.app.open-app', app_id: 'storage', params,
}, window.__MAVERICK_PLATFORM_ORIGIN__), params);
const file = (id, connection) => ({ id, file_id: id, path_id: id, provider: 'google_drive',
  connection_id: connection, drive_file_id: id, role: '', name: `${id}.txt`, relative_path: id,
  workspace_relative_path: '', extension: '.txt', size_bytes: 20, modified_at: '2026-09-01T00:00:00Z',
  content_type: 'text/plain', preview_kind: 'text', sha256: '', capabilities: { can_read: true, can_preview: true } });
const folder = (id, connection) => ({ id, provider: 'google_drive', connection_id: connection,
  drive_file_id: id, role: '', name: id, relative_path: id, workspace_relative_path: '', modified_at: '' });
let releaseSlow;
let releasePreview;
let slowStarted;
const slowRequest = new Promise(resolve => { slowStarted = resolve; });
// The disposable host deliberately has no provider credentials. This scenario
// never sends a turn; keep the selected fixture transcript composable so its
// real reference picker can be exercised without starting a provider.
await context.routeWebSocket(/\/ws\/runtime\/sessions\//, route => {
  const server = route.connectToServer();
  server.onMessage(message => {
    let frame;
    try { frame = JSON.parse(String(message)); } catch { route.send(message); return; }
    route.send(JSON.stringify(frame.type === 'runtime.snapshot'
      ? { ...frame, session: { ...frame.session, runtime_admission: null }, runtime_admission: null }
      : frame));
  });
});
await context.route('**/api/apps/storage/backend', async route => {
  const body = route.request().postDataJSON();
  reads.push({ action: body.action, connection: body.connection_id, folder: body.drive_file_id,
    query: body.query, parent: body.parent_drive_file_id, token: body.page_token, time: Date.now() });
  if (body.action === 'drive_list_connections') return route.fulfill({ json: { provider: 'google_drive', connections: [] } });
  if (!['drive_list_roots', 'drive_list_children', 'drive_search'].includes(body.action)) return route.continue();
  const connection = body.connection_id;
  if (connection === 'slow-account') {
    slowStarted();
    await new Promise(resolve => { releaseSlow = resolve; });
  }
  let files = [], folders = [], next = '';
  if (body.action === 'drive_search') {
    assert.equal(body.query, 'report');
    assert.equal(connection, 'account-b');
    files = [file(body.page_token ? 'search-result-two' : 'search-result-one', connection)];
    if (!body.page_token) next = 'search-page-two';
    else assert.equal(body.page_token, 'search-page-two');
  } else if (body.drive_file_id) {
    files = [file(`${body.drive_file_id}-file`, connection)];
  } else if (body.page_token) {
    assert.equal(body.page_token, 'root-page-two');
    files = [file(`${connection}-second`, connection)];
  } else {
    files = [file(`${connection}-first`, connection)];
    folders = [folder('Shared with me', connection), folder('Shared drive', connection)];
    next = 'root-page-two';
  }
  await route.fulfill({ json: { provider: 'google_drive', connection_id: connection, files, folders,
    incomplete_search: body.action === 'drive_search', pagination: { limit: body.limit, total: null,
      loaded_items: files.length + folders.length, has_more: Boolean(next), next_page_token: next } } });
});
try {
  const login = await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: 'fixture-admin', password: 'fixture-only-password' },
  });
  assert(login.ok());
  await page.goto(`${baseUrl}/app/storage?role=generated&folder_relative_path=previews`, { waitUntil: 'domcontentloaded' });
  const iframe = page.locator('iframe.bs-workspace-app-frame.is-active');
  await iframe.waitFor();
  storage = await (await iframe.elementHandle()).contentFrame();
  await storage.getByRole('button', { name: 'Open large.txt', exact: true }).click();
  const preview = storage.locator('.preview-modal-body pre');
  await preview.waitFor();
  const text = await preview.textContent();
  assert(text.length > 8 * 1024 * 1024);
  const digest = createHash('sha256').update(text).digest('hex');
  const largeMediaUrl = media.at(-1)?.url;
  assert(largeMediaUrl && new URL(largeMediaUrl).searchParams.has('stable_storage_file_id'),
    'Large preview must use the authenticated stream and stable file identity.');
  const downloading = page.waitForEvent('download');
  await storage.getByRole('button', { name: 'Download file', exact: true }).click();
  const download = await downloading;
  assert.equal(download.suggestedFilename(), 'large.txt');
  assert.equal(createHash('sha256').update(readFileSync(await download.path())).digest('hex'), digest);
  await storage.getByRole('button', { name: 'Close preview', exact: true }).click();
  const beforeReopen = media.filter(read => read.url === largeMediaUrl).length;
  await storage.getByRole('button', { name: 'Open large.txt', exact: true }).click();
  await preview.waitFor();
  assert.equal(createHash('sha256').update(await preview.textContent()).digest('hex'), digest);
  assert(media.filter(read => read.url === largeMediaUrl).length > beforeReopen,
    'Oversized completed previews must not enter the small-value RAM cache.');
  await storage.getByRole('button', { name: 'Close preview', exact: true }).click();

  let previewStarted;
  const pendingPreview = new Promise(resolve => { previewStarted = resolve; });
  await context.route(url => url.href === largeMediaUrl, async route => {
    previewStarted();
    await new Promise(resolve => { releasePreview = resolve; });
    await route.fulfill({ status: 200, contentType: 'text/plain', body: 'OBSOLETE PREVIEW' });
  });
  await storage.getByRole('button', { name: 'Open large.txt', exact: true }).click();
  await pendingPreview;
  await storage.getByRole('button', { name: 'Close preview', exact: true }).click();
  await storage.getByRole('button', { name: 'Open small.txt', exact: true }).click();
  await storage.getByText('Complete small preview.', { exact: true }).waitFor();
  releasePreview();
  await sleep(250);
  assert.equal(await preview.textContent(), 'Complete small preview.\n');
  assert.equal(await storage.locator('.storage-error').count(), 0);
  await storage.getByRole('button', { name: 'Close preview', exact: true }).click();

  await navigate({ provider: 'google_drive', connection_id: 'account-a' });
  await storage.getByRole('button', { name: 'Open account-a-first.txt', exact: true }).waitFor();
  await storage.getByRole('button', { name: 'Load more', exact: true }).click();
  await storage.getByRole('button', { name: 'Open account-a-second.txt', exact: true }).waitFor();
  for (const id of ['Shared with me', 'Shared drive']) {
    await navigate({ provider: 'google_drive', connection_id: 'account-a', drive_file_id: id });
    await storage.getByRole('button', { name: `Open ${id}-file.txt`, exact: true }).waitFor();
  }
  await navigate({ provider: 'google_drive', connection_id: 'slow-account' });
  await slowRequest;
  await navigate({ provider: 'google_drive', connection_id: 'account-b' });
  await storage.getByRole('button', { name: 'Open account-b-first.txt', exact: true }).waitFor();
  releaseSlow();
  await sleep(250);
  assert.equal(await storage.getByRole('button', { name: 'Open slow-account-first.txt', exact: true }).count(), 0);
  const search = storage.getByPlaceholder('Search in Storage');
  await search.pressSequentially('report', { delay: 15 });
  await storage.getByRole('button', { name: 'Open search-result-one.txt', exact: true }).waitFor();
  assert.equal(reads.filter(read => read.action === 'drive_search').length, 1, 'Typing must produce one debounced query.');
  await storage.getByText('Drive returned partial results. Open a folder to narrow the search.', { exact: true }).waitFor();
  await storage.getByRole('button', { name: 'Load more', exact: true }).click();
  await storage.getByRole('button', { name: 'Open search-result-two.txt', exact: true }).waitFor();
  assert.equal(reads.filter(read => read.action === 'drive_search').length, 2);
  assert.equal(reads.filter(read => ['drive_preview', 'render_thumbnail'].includes(read.action)).length, 0,
    'Browsing must not start thumbnail or preview requests.');
  assert.equal(await storage.locator('.storage-error').count(), 0);
  await navigate({ role: 'generated', folder_relative_path: 'previews', picker_mode: 'fitness-coach-media',
    picker_return_app_id: 'fitness-coach', picker_accept: 'video' });
  await storage.getByRole('button', { name: 'Open fixture-video.webm', exact: true }).click();
  await storage.locator('.preview-modal-body video').waitFor();
  await storage.getByRole('button', { name: 'Use video', exact: true }).click();
  await page.waitForURL(url => url.pathname.startsWith('/app/fitness-coach'));
  const fitnessElement = page.locator('iframe.bs-workspace-app-frame.is-active[title="Fitness Coach viewport"]');
  await fitnessElement.waitFor();
  const fitness = await (await fitnessElement.elementHandle()).contentFrame();
  await fitness.getByText('fixture-video.webm', { exact: true }).first().waitFor();
  const selectedVideo = await fitness.locator('.media-picker').innerText();
  assert(selectedVideo.includes('fixture-video.webm'));

  await fitness.evaluate(() => window.parent.postMessage({ type: 'maverick.app.open-app', app_id: 'chat' },
    window.__MAVERICK_PLATFORM_ORIGIN__));
  await page.waitForURL(url => url.pathname === '/app/chat');
  const chatElement = page.locator('iframe.bs-workspace-app-frame.is-active[title="Chat viewport"]');
  await chatElement.waitFor();
  const chat = await (await chatElement.elementHandle()).contentFrame();
  await chat.getByRole('button', { name: 'Apps and references', exact: true }).click();
  await chat.getByRole('searchbox', { name: 'Search apps and references', exact: true }).fill('small.txt');
  await chat.getByRole('option').filter({ hasText: 'small.txt' }).first().click();
  await chat.waitForFunction(() => document.querySelector('[role="textbox"]')?.textContent.includes('small.txt'));
  const reference = await chat.locator('[role="textbox"]').first().textContent();
  assert(reference.includes('small.txt'));
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ schema: 1, boundary: 'authenticated-disposable-chromium', browser: browser.version(),
    local_preview_bytes: text.length, local_preview_download_sha256: digest, oversized_preview_not_cached: true,
    cancelled_preview_stale_result_ignored: true, drive_boundary: 'deterministic Storage backend contract interception; no Google account',
    drive_account_switch_stale_result_ignored: true, drive_root_and_search_pagination: true,
    drive_shared_folder_navigation: true, drive_search_debounced: true, drive_incomplete_search_visible: true,
    fitness_video_picker_round_trip: true, chat_storage_reference_picker: true,
    drive_eager_previews: 0, reads, media, errors, physical_device_gate: 'not-tested' }, null, 2));
} catch (error) {
  const frames = await Promise.all(page.frames().map(async frame => ({ url: frame.url(),
    text: (await frame.locator('body').innerText().catch(() => '')).slice(0, 500),
    messages: await frame.evaluate(() => window.__MAVERICK_PERFORMANCE_MESSAGES__ || []).catch(() => []),
  })));
  throw new Error(`${error.message}; frames=${JSON.stringify(frames)}; errors=${JSON.stringify(errors)}`);
} finally {
  releasePreview?.();
  releaseSlow?.();
  await context.close();
  await browser.close();
}
