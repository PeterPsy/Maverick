import { expect, test } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { backend, mount } from './backend_fixture';

let dataRoot: string;
test.beforeEach(() => { dataRoot = mkdtempSync(`${tmpdir()}/crm-vnext-e2e-`); });
test.afterEach(() => { rmSync(dataRoot, { recursive: true, force: true }); });

test('creates a conversation, connects a person and links the selected Mail provider', async ({ page }) => {
  await mount(page, dataRoot);
  await page.getByRole('navigation', { name: 'CRM workspace' }).getByRole('button', { name: 'Conversations', exact: true }).click();
  await page.getByRole('button', { name: 'New conversation thread' }).click();
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).fill('Quarterly relationship review');
  await page.getByRole('dialog').getByLabel('Notes / content').fill('Agree the next step with the customer.');
  await page.getByRole('dialog').getByRole('button', { name: 'Save record' }).click();
  await page.getByRole('button', { name: /Quarterly relationship review/ }).click();
  await expect(page.getByRole('heading', { name: 'Quarterly relationship review' })).toBeVisible();
  await page.getByText('Connect a CRM record', { exact: true }).click();
  await page.locator('select[name="target_id"]').selectOption('contact_ada');
  await page.locator('input[name="relationship"]').fill('participant');
  await page.getByRole('button', { name: 'Link record', exact: true }).click();
  await expect(page.getByRole('button', { name: /Contact · participant Ada Example/ })).toBeVisible();
  await page.getByText('Connect a Maverick app record', { exact: true }).click();
  await page.locator('select[name="provider_alias"]').selectOption('mail');
  await page.locator('input[name="source_entity_type"]').fill('email_thread');
  await page.locator('input[name="source_entity_id"]').fill('provider_thread_123');
  await page.getByRole('button', { name: 'Link provider record' }).click();
  await page.getByRole('button', { name: 'Refresh links' }).click();
  await expect(page.getByText('provider_thread_123', { exact: true })).toBeVisible();
  const exported = backend(dataRoot, { action: 'crm.export' }).body.export;
  expect(exported.external_refs[0].source_app_id).toBe('test-mail');
  expect(exported.record_links).toHaveLength(1);
});

test('campaign planning persists variants without delivery', async ({ page }) => {
  await mount(page, dataRoot);
  await page.getByRole('navigation', { name: 'CRM workspace' }).getByRole('button', { name: 'Campaigns', exact: true }).click();
  await page.getByRole('button', { name: 'New campaign', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).fill('Customer check-in');
  await page.getByRole('dialog').getByRole('button', { name: 'Save record' }).click();
  await page.getByRole('button', { name: /Customer check-in/ }).click();
  await page.getByRole('button', { name: 'New campaign variant' }).click();
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).fill('Personal introduction');
  await page.getByRole('dialog').getByLabel('Notes / content').fill('A message to review, not to send.');
  await page.getByRole('dialog').getByRole('button', { name: 'Save record' }).click();
  await expect(page.getByRole('button', { name: /Personal introduction/ })).toBeVisible();
  const exported = backend(dataRoot, { action: 'crm.export' }).body.export;
  expect(exported.campaigns[0].status).toBe('draft');
  expect(exported.campaign_variants).toHaveLength(1);
});

test('import requires a current simulation before writing', async ({ page }) => {
  await mount(page, dataRoot);
  await page.getByRole('navigation', { name: 'CRM workspace' }).getByRole('button', { name: 'Import', exact: true }).click();
  const apply = page.getByRole('button', { name: '2. Apply reviewed import' });
  await expect(apply).toBeDisabled();
  await page.getByLabel('Source content').fill('id,display_name,email\nnew,New Person,new@example.test');
  await page.getByRole('button', { name: '1. Simulate import' }).click();
  await expect(apply).toBeEnabled();
  expect(backend(dataRoot, { action: 'crm.export' }).body.export.contacts).toHaveLength(1);
  await page.getByLabel('Source identity').fill('changed-source');
  await expect(apply).toBeDisabled();
  await page.getByRole('button', { name: '1. Simulate import' }).click();
  await expect(apply).toBeEnabled();
  await apply.click();
  await expect(page.getByRole('heading', { name: 'Import committed' })).toBeVisible();
  expect(backend(dataRoot, { action: 'crm.export' }).body.export.contacts).toHaveLength(2);
});

test('overview is responsive and shows live follow-up completion', async ({ page }, testInfo) => {
  await mount(page, dataRoot);
  await page.getByRole('navigation', { name: 'CRM workspace' }).getByRole('button', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'The relationship workspace' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('crm-vnext-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: 'Complete Prepare next conversation' }).click();
  await expect(page.getByText('Nothing waiting on you')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('crm-vnext-mobile.png'), fullPage: true });
});
