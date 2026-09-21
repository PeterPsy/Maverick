/** Real isolated app frames; this driver refuses live workspaces. */
import assert from 'node:assert/strict';
import { baseUrl, chromium, executablePath } from './performance_browser_support.mjs';

const browser = await chromium.launch({ headless: true, executablePath: executablePath() });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
context.setDefaultTimeout(15_000);
await context.addInitScript(() => {
  window.__lifecycleTrace = [];
  window.addEventListener('message', ({ data }) => {
    if (!['maverick.app.hibernate', 'maverick.app.hibernated', 'maverick.app.resume', 'maverick.app.resumed',
      'maverick.app.visibility-changed', 'maverick.app.events-resync'].includes(data?.type)) return;
    window.__lifecycleTrace.push({ type: data.type, app_id: data.app_id, visible: data.visible,
      files: data.snapshot?.state?.files, time: Date.now() });
  });
});
const page = await context.newPage();
const errors = [];
const catalogReads = [];
const calendarReads = [];
page.on('request', request => {
  if (request.url().includes('/api/apps/calendar/backend')) {
    const body = request.postDataJSON();
    calendarReads.push({ action: body?.action, frame: request.frame().url().split(/[?#]/)[0], time: Date.now() });
  }
  if (!request.url().includes('/api/apps/storage/backend')) return;
  const body = request.postDataJSON();
  if (body?.action === 'catalog') catalogReads.push({ offset: body.offset, folder: body.folder_path, time: Date.now() });
});
page.on('pageerror', error => errors.push(error.message));
const sockets = new Set();
const historyPages = [];
page.on('websocket', socket => {
  if (socket.url().includes('/ws/runtime/sessions/performance-chat-history')) {
    socket.on('framereceived', ({ payload }) => {
      const frame = JSON.parse(String(payload));
      if (frame.type === 'runtime.history.page' || frame.type === 'runtime.snapshot') {
        historyPages.push({ type: frame.type, direction: frame.direction, count: frame.events.length,
          first: frame.events[0]?.event_id, last: frame.events.at(-1)?.event_id });
      }
    });
  }
  if (!socket.url().includes('/api/apps/events/ws')) return;
  sockets.add(socket);
  socket.on('close', () => sockets.delete(socket));
});
async function activeFrame(appId) {
  const titles = { chat: 'Chat', storage: 'Storage', calendar: 'Calendar' };
  const selector = 'iframe.bs-workspace-app-frame.is-active' + (appId ? `[title="${titles[appId]} viewport"]` : '');
  const element = page.locator(selector);
  await element.waitFor({ state: 'visible', timeout: 30_000 });
  const handle = await element.elementHandle();
  return handle.contentFrame();
}
async function openApp(appId, params = {}) {
  const frame = await activeFrame();
  await frame.evaluate(({ appId, params }) => window.parent.postMessage({
    type: 'maverick.app.open-app', app_id: appId, params,
  }, window.__MAVERICK_PLATFORM_ORIGIN__), { appId, params });
  await page.waitForURL(url => url.pathname === `/app/${appId}`, { timeout: 30_000 });
  const next = await activeFrame(appId);
  await next.waitForLoadState('domcontentloaded');
  return next;
}
try {
  const response = await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: 'fixture-admin', password: 'fixture-only-password' },
  });
  assert(response.ok(), `Fixture login failed: ${response.status()}`);
  const registry = await (await context.request.get(`${baseUrl}/api/apps`)).json();
  for (const appId of ['chat', 'storage']) {
    assert.equal(registry.items.find(app => app.app_id === appId)?.frontend_resumable, true,
      `${appId} fixture must enable the hibernation contract.`);
  }
  await page.goto(`${baseUrl}/app/chat`, { waitUntil: 'domcontentloaded' });
  const chat = await activeFrame('chat');
  const composer = chat.getByRole('textbox').first();
  await composer.fill('Keep this unsent draft across hibernation.', { timeout: 45_000 });
  await openApp('storage');
  await openApp('calendar');
  await page.locator('iframe[title="Chat viewport"]').waitFor({ state: 'detached', timeout: 10_000 });
  const resumed = await openApp('chat');
  await resumed.waitForFunction(() => [...document.querySelectorAll('[role="textbox"]')]
    .some(element => element.textContent === 'Keep this unsent draft across hibernation.'), null, { timeout: 30_000 });
  const storage = await openApp('storage', { role: 'generated', folder_relative_path: 'reading' });
  await storage.getByRole('button', { name: 'Sort: Date', exact: true }).click();
  await storage.getByRole('menuitemradio', { name: 'Name', exact: true }).click();
  await storage.getByRole('button', { name: 'Open report-000000.md', exact: true }).waitFor();
  await storage.getByRole('button', { name: 'Load more', exact: true }).click();
  await storage.getByRole('button', { name: 'Open report-000199.md', exact: true }).waitFor();
  await storage.getByRole('button', { name: 'Open report-000001.md', exact: true }).click({ delay: 650 });
  await storage.getByRole('button', { name: 'Deselect report-000001.md', exact: true }).first().waitFor();
  const scrollTop = await storage.locator('.storage-browser').evaluate(element => {
    element.scrollTop = 650;
    return element.scrollTop;
  });
  assert(scrollTop > 0, 'Storage fixture must exercise a real scroll position.');
  await openApp('chat');
  await openApp('calendar');
  await page.locator('iframe[title="Storage viewport"]').waitFor({ state: 'detached', timeout: 10_000 });
  const restoredStorage = await openApp('storage');
  await restoredStorage.getByRole('button', { name: 'Deselect report-000001.md', exact: true }).first().waitFor();
  await restoredStorage.getByRole('button', { name: 'Select report-000199.md', exact: true }).first().waitFor();
  await restoredStorage.waitForFunction(top => Math.abs(document.querySelector('.storage-browser').scrollTop - top) < 2,
    scrollTop, { timeout: 15_000 });
  let writing = true;
  const uploadTimes = [];
  let uploadError;
  const uploads = (async () => {
    for (let index = 0; (writing || index < 8) && index < 100; index++) {
      const started = Date.now();
      const write = await context.request.post(`${baseUrl}/api/apps/storage/backend`, { headers: { Origin: baseUrl }, data: {
        action: 'write_file', role: 'generated', relative_path: `uploads/unrelated-${index}.md`, content: '# Concurrent fixture',
        _app_secret_request: { logical_names: [], required: false },
      } });
      assert(write.ok(), `Fixture upload failed: ${write.status()}`);
      uploadTimes.push({ started, completed: Date.now() });
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  })().catch(error => { uploadError = error; });
  try {
    for (let index = 0; index < 2; index++) {
      await restoredStorage.getByRole('button', { name: 'Load more', exact: true }).click();
      const last = index === 0 ? '000299' : '000349';
      await restoredStorage.getByRole('button', { name: `Select report-${last}.md`, exact: true }).first().waitFor();
    }
  } finally { writing = false; await uploads; }
  if (uploadError) throw uploadError;
  assert(uploadTimes.length >= 8, 'Continuous writer did not complete its fixture workload.');
  await restoredStorage.waitForFunction(() => document.querySelector('.content-counts')?.textContent.includes('350 files'));
  assert.equal(await restoredStorage.locator('.animated-file-item').count(), 350);
  assert.equal(await restoredStorage.locator('.storage-error').count(), 0);
  let historyChat = await openApp('chat', { thread_id: 'performance-chat-thread' });
  await historyChat.getByText('Fixture request 02999', { exact: true }).waitFor({ timeout: 30_000 });
  const transcript = historyChat.locator('.chatapp-chat-scroll__inner');
  let iterations = 0;
  let maxRows = 0;
  while (!await historyChat.getByRole('button', { name: 'Load newer messages', exact: true }).count() && iterations++ < 100) {
    await transcript.evaluate(element => { element.scrollTop = 0; element.dispatchEvent(new Event('scroll')); });
    await page.waitForTimeout(200);
    maxRows = Math.max(maxRows, await historyChat.locator('[data-transcript-row]:not([hidden])').count());
  }
  assert(iterations < 100, `Cold data never evicted: ${JSON.stringify(historyPages)}`);
  const visibleRows = await historyChat.locator('[data-transcript-row]:not([hidden])').count();
  assert(visibleRows < 40, `History DOM grew to ${visibleRows} rows after eviction.`);
  const readingAnchor = await historyChat.evaluate(() => {
    const viewport = document.querySelector('.chatapp-chat-scroll__inner');
    const top = viewport.getBoundingClientRect().top;
    const row = [...viewport.querySelectorAll('[data-transcript-row]:not([hidden])')]
      .find(element => element.getBoundingClientRect().bottom > top && element.getBoundingClientRect().top < top + viewport.clientHeight);
    return row ? { id: row.dataset.transcriptRow, offset: row.getBoundingClientRect().top - top } : null;
  });
  assert(readingAnchor, 'History must have an actual visible reading anchor.');
  await openApp('storage');
  await openApp('calendar');
  await page.locator('iframe[title="Chat viewport"]').waitFor({ state: 'detached', timeout: 10_000 });
  historyChat = await openApp('chat');
  await historyChat.waitForFunction(anchor => {
    const viewport = document.querySelector('.chatapp-chat-scroll__inner');
    const row = [...document.querySelectorAll('[data-transcript-row]:not([hidden])')]
      .find(element => element.dataset.transcriptRow === anchor.id);
    return viewport && row && Math.abs(row.getBoundingClientRect().top - viewport.getBoundingClientRect().top - anchor.offset) < 3;
  }, readingAnchor, { timeout: 30_000 });
  await historyChat.getByRole('button', { name: 'Load newer messages', exact: true }).click();
  for (let attempt = 0; !historyPages.some(frame => frame.direction === 'after') && attempt < 30; attempt++) await page.waitForTimeout(100);
  assert(historyPages.some(frame => frame.direction === 'after'), 'Newer history did not use forward paging.');
  await historyChat.getByRole('button', { name: 'Jump to latest message', exact: true }).click();
  await historyChat.getByText('Fixture request 02999', { exact: true }).waitFor();
  assert(historyPages.some(frame => frame.direction === 'latest'), 'Jump to latest did not replace the data window.');
  const calendar = await openApp('calendar');
  await calendar.locator('.calendar-board').waitFor();
  await page.waitForTimeout(500);
  await openApp('storage');
  await page.waitForTimeout(1_000);
  const hiddenReads = calendarReads.length;
  await page.waitForTimeout(1_000);
  assert.equal(calendarReads.length, hiddenReads, 'Hidden Calendar issued background reads.');
  const resumedAt = Date.now();
  await openApp('calendar');
  await page.waitForTimeout(750);
  const resumedWindows = calendarReads.filter(read => read.time >= resumedAt && read.action === 'pwa.read_model');
  assert.equal(resumedWindows.length, 1, 'Calendar resume must perform one useful window refresh.');
  assert.equal(await calendar.locator('.calendar-error').count(), 0, 'Calendar displayed an intentional cancellation error.');
  await page.setViewportSize({ width: 600, height: 900 });
  await page.getByRole('button', { name: 'Apri sidebar', exact: true }).click();
  const isAccountSidebar = frame => frame.url().includes('calendar-sidebar') && !frame.url().includes('calendar-sidebar-footer');
  const calendarSidebar = page.frames().find(isAccountSidebar)
    ?? await page.waitForEvent('framenavigated', { predicate: isAccountSidebar });
  assert(calendarSidebar, 'Calendar account sidebar was not mounted.');
  await calendarSidebar.locator('.calendar-sidebar-widget').waitFor();
  await page.waitForTimeout(750);
  await page.getByRole('button', { name: 'Chiudi sidebar', exact: true }).click();
  await page.waitForTimeout(1_000);
  const widgetReads = () => calendarReads.filter(read => read.frame.includes('calendar-sidebar'));
  const closedWidgetReads = widgetReads().length;
  await page.waitForTimeout(1_000);
  assert.equal(widgetReads().length, closedWidgetReads, 'Closed sidebar issued background reads.');
  assert.equal(calendarSidebar.isDetached(), false, 'Closing sidebar destroyed the active widget state.');
  const sidebarResumedAt = Date.now();
  await page.getByRole('button', { name: 'Apri sidebar', exact: true }).click();
  await page.waitForTimeout(750);
  const resumedAccountReads = widgetReads().filter(read => read.time >= sidebarResumedAt && read.action === 'list');
  assert.equal(resumedAccountReads.length, 1, 'Reopening sidebar must perform one account refresh.');
  assert.equal(calendarSidebar.isDetached(), false, 'Reopening sidebar replaced the retained widget.');
  assert.equal(sockets.size, 1, 'Only the Shell should own app events.');
  assert.deepEqual(errors, [], 'App frames emitted browser errors.');
  process.stdout.write(JSON.stringify({ schema: 1, boundary: 'authenticated-disposable-chromium',
    browser: browser.version(), fixture_files: 350, chat_draft_hibernation: 'passed',
    storage_folder_sort_selection_paging_scroll_hibernation: 'passed', shared_app_event_socket_count: sockets.size,
    storage_pagination_during_other_folder_writes: 'passed', catalog_reads: catalogReads, continuous_uploads: uploadTimes,
    chat_bidirectional_data_window: 'passed', chat_history_pages: historyPages, chat_max_visible_rows: maxRows,
    chat_history_reading_anchor_hibernation: 'passed', chat_reading_anchor: readingAnchor,
    calendar_hidden_reads: 0, calendar_resume_window_reads: resumedWindows.length, calendar_reads: calendarReads,
    calendar_sidebar_hidden_reads: 0, calendar_sidebar_resume_reads: resumedAccountReads.length,
    calendar_sidebar_retains_frame: true,
    errors, physical_device_gate: 'not-tested' }, null, 2) + '\n');
} catch (error) {
  const frames = await Promise.all(page.frames().map(async frame => ({
    name: frame.name(), url: frame.url().split(/[?#]/)[0],
    text: (await frame.locator('body').innerText().catch(() => '')).slice(0, 1000),
    trace: await frame.evaluate(() => window.__lifecycleTrace?.slice(-12)).catch(() => []),
  })));
  throw new Error(`${error.message}; fixture frames=${JSON.stringify(frames)}; errors=${JSON.stringify(errors)}; reads=${JSON.stringify(catalogReads)}`);
} finally {
  await context.close();
  await browser.close();
}
