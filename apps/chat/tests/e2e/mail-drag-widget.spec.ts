import { expect, test, type Page } from '@playwright/test';

async function openFixture(page: Page, baseURL: string) {
  const host = new URL('/apps/chat/tests/mail-drag/host.html', baseURL);
  host.hostname = 'shell.localhost';
  await page.goto(host.href);
  const source = page.frameLocator('#mail');
  const target = page.frameLocator('#chat');
  await expect(source.getByRole('button', { name: 'Synthetic email' })).toBeVisible();
  await expect(target.getByRole('textbox')).toBeEditable();
  return { source, target };
}

async function moveMailToComposer(page: Page, source: ReturnType<Page['frameLocator']>, target: ReturnType<Page['frameLocator']>) {
  const from = (await source.getByRole('button', { name: 'Synthetic email' }).boundingBox())!;
  const to = (await target.getByRole('textbox').boundingBox())!;
  await page.mouse.move(from.x + 40, from.y + 30);
  await page.mouse.down();
  await page.mouse.move(from.x + 55, from.y + 30, { steps: 3 });
  await page.mouse.move(to.x + 40, to.y + 15, { steps: 12 });
}

test.use({ viewport: { width: 1280, height: 800 } });

test('drops Mail into the open widget composer across isolated origins exactly once', async ({ page, baseURL }) => {
  const { source, target } = await openFixture(page, baseURL!);
  await target.getByRole('textbox').fill('Existing draft ');
  await moveMailToComposer(page, source, target);
  await page.mouse.up();
  await expect(target.getByRole('textbox')).toContainText('Synthetic email');
  await expect(target.getByRole('textbox')).toContainText('Existing draft');
  const references = JSON.parse((await target.getByTestId('references').textContent())!);
  expect(references).toEqual([expect.objectContaining({ app_id: 'mail', entity_type: 'email_thread', entity_id: 'thread-fixture' })]);
  await expect(source.locator('#opened')).toHaveText('0');
});

test('Escape cancels a Mail drag over the composer', async ({ page, baseURL }) => {
  const { source, target } = await openFixture(page, baseURL!);
  await moveMailToComposer(page, source, target);
  await page.keyboard.press('Escape');
  await page.mouse.up();
  await expect(source.locator('#row')).toHaveAttribute('data-dragging', '');
  await expect(target.getByRole('textbox')).toHaveText('');
  await expect(target.getByTestId('references')).toHaveText('[]');
});

test('ordinary Mail clicks still open the email and drops outside Chat do not insert references', async ({ page, baseURL }) => {
  const { source, target } = await openFixture(page, baseURL!);
  await source.getByRole('button').click();
  await expect(source.locator('#opened')).toHaveText('1');
  const from = (await source.getByRole('button').boundingBox())!;
  await page.mouse.move(from.x + 30, from.y + 30);
  await page.mouse.down();
  await page.mouse.move(from.x + 45, from.y + 30, { steps: 3 });
  await page.mouse.move(from.x + 40, from.y + 160, { steps: 10 });
  await page.mouse.up();
  await expect(target.getByRole('textbox')).toHaveText('');
});
