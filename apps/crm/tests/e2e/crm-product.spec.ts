import { expect, test } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { backend, mount, navigate } from './backend_fixture';

let dataRoot: string;
test.beforeEach(() => { dataRoot = mkdtempSync(`${tmpdir()}/crm-product-e2e-`); });
test.afterEach(() => { rmSync(dataRoot, { recursive: true, force: true }); });
const create = (entity: string, values: Record<string, unknown>) => backend(dataRoot, { action: 'crm.create_extension_record', entity_type: entity, ...values }).body.record;

test('daily tasks use real horizons, retain completed work and open a contextual inspector', async ({ page }) => {
  await mount(page, dataRoot);
  const soon = new Date(); soon.setDate(soon.getDate() + 3);
  backend(dataRoot, { action: 'crm.create_task', title: 'Next week call', due_at: soon.toISOString() });
  backend(dataRoot, { action: 'crm.create_task', title: 'Undated follow-up' });
  await navigate(page, 'Tasks');
  await expect(page.getByRole('button', { name: 'Prepare next conversation', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next week call', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '1–7 days', exact: true }).click();
  await page.getByRole('button', { name: 'Next week call', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Record inspector' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Tasks', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByRole('button', { name: 'Complete Next week call', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Next week call', exact: true })).toHaveCount(0);
  await page.getByLabel('Task status').selectOption('done');
  await expect(page.getByRole('button', { name: 'Reopen Next week call' })).toBeVisible();
  await page.getByRole('button', { name: 'No date', exact: true }).click();
  await page.getByLabel('Task status').selectOption('open');
  await expect(page.getByRole('button', { name: 'Undated follow-up', exact: true })).toBeVisible();
});

test('thread state, company cards and expense decimal amounts use existing generic records', async ({ page }) => {
  create('conversation_thread', { title: 'Waiting for customer', status: 'waiting', channel: 'email' });
  backend(dataRoot, { action: 'crm.create_account', name: 'Example Company', domain: 'example.test' });
  create('expense', { title: 'Dollar expense', amount_minor: 5700, currency: 'USD' });
  await mount(page, dataRoot);
  await navigate(page, 'Threads');
  await expect(page.getByRole('button', { name: /Waiting for customer/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Waiting (1)', exact: true }).click();
  await expect(page.getByRole('button', { name: /Waiting for customer/ })).toBeVisible();
  await navigate(page, 'Companies');
  await page.getByRole('button', { name: /Example Company/ }).click();
  await expect(page.getByRole('region', { name: 'Example Company' })).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await navigate(page, 'Expenses');
  await page.getByRole('button', { name: 'New expense' }).click();
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).focus();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'New expense' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Title', { exact: true }).fill('Train ticket');
  await dialog.getByLabel('Amount', { exact: true }).fill('12.34');
  await dialog.getByLabel('Incurred at').fill('2030-10-01');
  await dialog.getByRole('button', { name: 'Save record' }).click();
  await expect(page.getByRole('button', { name: 'Train ticket', exact: true })).toBeVisible();
  const expenses = backend(dataRoot, { action: 'crm.export' }).body.export.expenses;
  expect(expenses.find((item: any) => item.title === 'Train ticket').amount_minor).toBe(1234);
  await expect(page.getByText('TOTAL · EUR', { exact: true })).toBeVisible();
  await expect(page.getByText('TOTAL · USD', { exact: true })).toBeVisible();
});

test('calendar ranges, quality review and transcripts remain explicit read-only surfaces', async ({ page }) => {
  await mount(page, dataRoot, { calendar: 'calendar' });
  backend(dataRoot, { action: 'crm.link_external_ref', crm_entity_type: 'contact', crm_entity_id: 'contact_ada', source_app_id: 'calendar', source_entity_type: 'event', source_entity_id: 'meeting_future', title: 'Future customer meeting', metadata: { startTime: '2030-10-01T09:00:00Z', endTime: '2030-10-01T10:00:00Z', last_error: 'Provider unavailable' } }, { calendar: 'calendar' });
  backend(dataRoot, { action: 'crm.create_contact', display_name: 'Incomplete Person' });
  const before = backend(dataRoot, { action: 'crm.export' }).body.export;
  await navigate(page, 'Calendar');
  await page.getByLabel('Calendar starts on').fill('2030-10-01');
  await expect(page.getByRole('heading', { name: 'Future customer meeting' })).toBeVisible();
  await expect(page.getByText(/Provider unavailable · Last good snapshot retained/)).toBeVisible();
  await page.getByLabel('Calendar starts on').fill('2030-11-01');
  await expect(page.getByRole('heading', { name: 'Future customer meeting' })).toHaveCount(0);
  await navigate(page, 'Data quality');
  await expect(page.getByRole('button', { name: /Incomplete Person/ })).toBeVisible();
  await navigate(page, 'Transcripts');
  await expect(page.getByText('No transcription operations yet. No audio is processed automatically.')).toBeVisible();
  const after = backend(dataRoot, { action: 'crm.export' }).body.export;
  for (const table of ['contacts', 'external_refs', 'workflow_proposals', 'notes']) expect(after[table]).toEqual(before[table]);
});

test('dashboard mirrors brief, metrics and pipeline structure with Maverick colors on desktop and mobile', async ({ page }, testInfo) => {
  create('brief', { title: 'Relationship priorities', body: 'Follow up on the customer meeting.\nPrepare the next offer.', period_start: '2030-10-01', period_end: '2030-10-07' });
  backend(dataRoot, { action: 'crm.create_deal', name: 'Customer opportunity', value: 2000, currency: 'EUR', margin_minor: 50000 });
  backend(dataRoot, { action: 'crm.create_deal', name: 'USD opportunity', value: 1000, currency: 'USD', margin_minor: 20000 });
  await mount(page, dataRoot);
  await navigate(page, 'Dashboard');
  await expect(page.getByRole('heading', { name: 'Weekly brief' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Relationship priorities' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Pipeline by stage' })).toBeVisible();
  await page.getByLabel('Dashboard currency').selectOption('USD');
  await expect(page.getByRole('button', { name: /OPEN PIPELINE/ })).toContainText('1,000');
  await page.getByRole('button', { name: 'Margin', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('.product-page').evaluate((node) => node.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('crm-product-dashboard-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const searchBox = await page.getByRole('textbox', { name: 'Search CRM' }).boundingBox();
  expect(searchBox!.width).toBeGreaterThan(100);
  for (const name of ['Refresh workspace', 'New record']) {
    const bounds = await page.getByRole('button', { name, exact: true }).boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  }
  await page.locator('.product-page').evaluate((node) => node.scrollTo(0, 0));
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeInViewport();
  await expect(page.getByRole('heading', { name: 'Weekly brief' })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath('crm-product-dashboard-mobile.png'), fullPage: true });
  await navigate(page, 'People');
  await expect(page.getByRole('heading', { name: 'People', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Ada Example', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Ada Example' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('complementary', { name: 'Record inspector' })).toHaveCount(0);
});

test('mobile canvas reserves the Maverick shell header without creating page overflow', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mount(page, dataRoot);
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--maverick-shell-mobile-content-top-offset', '68px');
  });

  const layout = await page.locator('.product-main').evaluate((main) => {
    const topbar = main.querySelector<HTMLElement>('.crm-topbar');
    const records = main.querySelector<HTMLElement>('.records-view');
    if (!topbar || !records) throw new Error('Expected the CRM mobile layout to be mounted');
    const topbarBox = topbar.getBoundingClientRect();
    const recordsBox = records.getBoundingClientRect();
    return {
      mainBottom: main.getBoundingClientRect().bottom,
      topbarTop: topbarBox.top,
      topbarBottom: topbarBox.bottom,
      recordsTop: recordsBox.top,
      viewportHeight: innerHeight,
      viewportWidth: innerWidth,
      pageWidth: document.documentElement.scrollWidth,
    };
  });

  expect(layout.topbarTop).toBe(68);
  expect(layout.recordsTop).toBeGreaterThanOrEqual(layout.topbarBottom);
  expect(layout.mainBottom).toBeLessThanOrEqual(layout.viewportHeight);
  expect(layout.pageWidth).toBe(layout.viewportWidth);
  await page.screenshot({ path: testInfo.outputPath('crm-shell-mobile-layout.png'), fullPage: true });

  await page.getByRole('row').filter({ hasText: 'Ada Example' }).click();
  const inspectorTop = await page.getByRole('complementary', { name: 'Record inspector' }).evaluate((node) => node.getBoundingClientRect().top);
  expect(inspectorTop).toBe(130);
});

test('deal stages and proposal review are real mutations with separate approval and application', async ({ page }) => {
  await mount(page, dataRoot);
  backend(dataRoot, { action: 'crm.create_deal', name: 'Renewal opportunity', value: 2500 });
  const stage = backend(dataRoot, { action: 'bootstrap' }).body.pipeline_stages.find((item: any) => item.id === 'won');
  await navigate(page, 'Deals');
  await page.getByLabel('Stage for Renewal opportunity').selectOption(stage.id);
  await expect.poll(() => backend(dataRoot, { action: 'crm.export' }).body.export.deals[0].stage_id).toBe(stage.id);
  backend(dataRoot, { action: 'crm.meeting_outcome', entity_type: 'contact', entity_id: 'contact_ada', summary: 'Discussed the renewal.', idempotency_key: 'product-test-outcome', followups: [{ title: 'Review revised renewal' }] });
  await navigate(page, 'Proposals');
  const proposal = page.locator('.product-proposal').filter({ hasText: 'Review revised renewal' });
  await expect(proposal.getByRole('button', { name: 'Approve proposal' })).toBeDisabled();
  await proposal.getByRole('button', { name: 'Preview changes' }).click();
  await proposal.getByRole('button', { name: 'Approve proposal' }).click();
  expect(backend(dataRoot, { action: 'crm.export' }).body.export.tasks).toHaveLength(1);
  await proposal.getByRole('button', { name: 'Preview changes' }).click();
  await proposal.getByRole('button', { name: 'Apply approved proposal' }).click();
  await expect.poll(() => backend(dataRoot, { action: 'crm.export' }).body.export.tasks.length).toBe(2);
});
