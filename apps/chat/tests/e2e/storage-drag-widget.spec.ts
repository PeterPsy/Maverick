import { expect, test, type FrameLocator, type Page } from '@playwright/test';

async function openFixture(page: Page, baseURL: string, mode = 'file', targetRole = 'uploaded') {
  const host = new URL('/apps/chat/tests/storage-drag/host.html', baseURL);
  host.hostname = 'shell.localhost';
  host.searchParams.set('mode', mode);
  host.searchParams.set('target_role', targetRole);
  await page.goto(host.href);
  const source = page.frameLocator('#storage');
  const sidebar = page.frameLocator('#sidebar');
  const chat = page.frameLocator('#chat');
  await expect(source.getByTestId('opened')).toBeVisible();
  await expect(chat.getByRole('textbox')).toBeEditable();
  return { source, sidebar, chat };
}
function item(frame: FrameLocator, folder = false) {
  return frame.locator(folder ? '.folder-card-open' : '.animated-file-preview-button').first();
}
async function drag(page: Page, source: ReturnType<typeof item>, target: ReturnType<typeof item>) {
  const from = (await source.boundingBox())!;
  const to = (await target.boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 12, from.y + from.height / 2, { steps: 3 });
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 15 });
}

test.use({ viewport: { width: 1440, height: 900 } });
for (const mode of ['file', 'folder', 'selection', 'drive-file', 'drive-folder']) {
  test(`cites a Storage ${mode} in the widget across isolated origins exactly once`, async ({ page, baseURL }) => {
    const { source, chat } = await openFixture(page, baseURL!, mode);
    await chat.getByRole('textbox').fill('Existing draft ');
    await drag(page, item(source, mode.includes('folder')), chat.getByRole('textbox'));
    await page.mouse.up();
    await expect(chat.getByRole('textbox')).toContainText('Existing draft');
    await expect.poll(async () => JSON.parse((await chat.getByTestId('references').textContent())!).length).toBe(mode === 'selection' ? 2 : 1);
    const references = JSON.parse((await chat.getByTestId('references').textContent())!);
    expect(references.every((ref: { app_id: string }) => ref.app_id === 'storage')).toBe(true);
    expect(references.map((ref: { entity_type: string }) => ref.entity_type)).toEqual(mode === 'selection' ? ['file', 'folder'] : [mode.includes('folder') ? 'folder' : 'file']);
    if (mode === 'drive-file') expect(references[0].entity_id).toBe('drive-file-fixture');
    if (mode === 'drive-folder') expect(references[0].deep_link).toContain('connection_id=drive-fixture');
    await expect(source.getByTestId('opened')).toHaveText('0');
  });
}

test('Escape cancels a Storage drag and normal open/action clicks still work', async ({ page, baseURL }) => {
  const { source, chat } = await openFixture(page, baseURL!);
  await drag(page, item(source), chat.getByRole('textbox'));
  await page.keyboard.press('Escape');
  await page.mouse.up();
  await expect(chat.getByTestId('references')).toHaveText('[]');
  await item(source).click();
  await expect(source.getByTestId('opened')).toHaveText('1');
  await source.getByRole('button', { name: 'Show details for Synthetic document.txt' }).click();
  await expect(source.getByTestId('actions')).toHaveText('1');
});

test('Storage moves retain hover feedback inside the app and across the sidebar frame', async ({ page, baseURL }) => {
  const { source, sidebar, chat } = await openFixture(page, baseURL!);
  await drag(page, item(source), source.getByTestId('move-target'));
  await expect(source.getByTestId('hover')).toHaveText('ready');
  await page.mouse.up();
  await expect.poll(async () => JSON.parse((await source.getByTestId('moves').textContent())!).length).toBe(1);
  await drag(page, item(source), sidebar.getByTestId('move-target'));
  await expect(sidebar.getByTestId('hover')).toHaveText('ready');
  await page.mouse.up();
  await expect.poll(async () => JSON.parse((await sidebar.getByTestId('moves').textContent())!).length).toBe(1);
  await expect(chat.getByTestId('references')).toHaveText('[]');
  await drag(page, item(sidebar, true), chat.getByRole('textbox'));
  await page.mouse.up();
  await expect.poll(async () => JSON.parse((await chat.getByTestId('references').textContent())!).length).toBe(1);
});

test('Storage role markers still block moves from Uploaded to Generated', async ({ page, baseURL }) => {
  const { source, sidebar } = await openFixture(page, baseURL!, 'file', 'generated');
  await drag(page, item(source), sidebar.getByTestId('move-target'));
  await expect(sidebar.getByTestId('hover')).toHaveText('blocked');
  await page.mouse.up();
  await expect(sidebar.getByTestId('moves')).toHaveText('[]');
  await expect(source.getByTestId('opened')).toHaveText('0');
});
