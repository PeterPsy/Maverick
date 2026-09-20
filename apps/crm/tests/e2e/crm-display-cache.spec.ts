import { expect, test } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { backend, mount, navigate } from './backend_fixture';

let dataRoot: string;
test.beforeEach(() => { dataRoot = mkdtempSync(`${tmpdir()}/crm-display-cache-`); });
test.afterEach(() => { rmSync(dataRoot, { recursive: true, force: true }); });

test('relationship views use reviewed display reads, retain margin and send mutations only once', async ({ page }) => {
  backend(dataRoot, { action: 'crm.create_account', name: 'Display Company', domain: 'example.test' });
  backend(dataRoot, { action: 'crm.create_deal', name: 'Display Deal', value: 2000, currency: 'EUR', margin_minor: 50000 });
  await mount(page, dataRoot);
  const requests: Record<string, any>[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/api/apps/crm/backend')) requests.push(request.postDataJSON());
  });
  for (const [view, entity, name] of [
    ['People', 'contact', 'Ada Example'], ['Companies', 'account', 'Display Company'], ['Deals', 'deal', 'Display Deal'],
  ]) {
    await navigate(page, view);
    await expect(page.getByRole('button', { name, exact: entity !== 'account' })).toBeVisible();
    expect(requests.some((body) => body.action === 'pwa.read_model' && body.kind === 'records_table' && body.entity_type === entity && body.limit === 40)).toBe(true);
    expect(requests.some((body) => body.action === 'crm.records_table' && body.entity_type === entity)).toBe(false);
  }
  await expect(page.getByRole('row').filter({ hasText: 'Display Deal' }).locator('td').nth(3)).toContainText('500');
  await page.getByLabel('Stage for Display Deal').selectOption('won');
  await expect.poll(() => backend(dataRoot, { action: 'crm.export' }).body.export.deals[0].stage_id).toBe('won');
  expect(requests.filter((body) => body.action === 'crm.move_deal')).toHaveLength(1);
});

test('refresh preserves visible rows, while a new query clears them and fences late results', async ({ page }) => {
  await mount(page, dataRoot);
  await navigate(page, 'People');
  const ada = page.getByRole('button', { name: 'Ada Example', exact: true });
  await expect(ada).toBeVisible();
  let held = 0;
  let release!: () => void;
  let delivered!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const settled = new Promise<void>((resolve) => { delivered = resolve; });
  await page.route('**/api/apps/crm/backend', async (route) => {
    const body = route.request().postDataJSON();
    if (body.action === 'pwa.read_model' && body.kind === 'records_table' && body.entity_type === 'contact' && !body.query) {
      const result = backend(dataRoot, body);
      held++;
      await pending;
      await route.fulfill({ status: result.status, json: result.body }).catch(() => undefined);
      delivered();
    } else await route.fallback();
  });
  try {
    await page.getByRole('button', { name: 'Refresh view', exact: true }).click();
    await expect.poll(() => held).toBeGreaterThan(0);
    await expect(ada).toBeVisible();
    await page.getByRole('textbox', { name: 'Search CRM' }).fill('No matching person');
    await expect(ada).toHaveCount(0);
    await expect(page.getByText('No records in this view. Add a record or change your filters.')).toBeVisible();
  } finally { release(); }
  await settled;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(ada).toHaveCount(0);
});

test('authorization denial on display refresh removes previously visible customer rows', async ({ page }) => {
  await mount(page, dataRoot);
  await navigate(page, 'People');
  const ada = page.getByRole('button', { name: 'Ada Example', exact: true });
  await expect(ada).toBeVisible();
  await page.route('**/api/apps/crm/backend', async (route) => {
    const body = route.request().postDataJSON();
    if (body.action === 'pwa.read_model' && body.kind === 'records_table' && body.entity_type === 'contact') {
      await route.fulfill({ status: 403, json: { error: 'forbidden' } });
    } else await route.fallback();
  });
  await page.getByRole('button', { name: 'Refresh view', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('403');
  await expect(ada).toHaveCount(0);
});
