import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { backend } from './backend_fixture';

let dataRoot: string;
test.beforeEach(() => { dataRoot = mkdtempSync(`${tmpdir()}/crm-public-navigation-e2e-`); });
test.afterEach(() => { rmSync(dataRoot, { recursive: true, force: true }); });

async function mountPublicCrm(page: Page) {
  backend(dataRoot, { action: 'crm.create_contact', id: 'contact_ada', display_name: 'Ada Example', email: 'ada@example.test' });
  await page.route('**/api/apps/crm/backend', async (route) => {
    const result = backend(dataRoot, route.request().postDataJSON());
    await route.fulfill({ status: result.status, contentType: 'application/json', body: JSON.stringify(result.body) });
  });
  await page.route('**/apps/crm/', async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replace('<html lang="en">', '<html lang="en" data-crm-public-access="read-only">');
    await route.fulfill({ response, body: html });
  });
  await page.goto('/apps/crm/');
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
}

test('public CRM uses Maverick sidebar chrome without an app rail and persists its theme', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mountPublicCrm(page);

  const navigation = page.getByRole('complementary', { name: 'CRM navigation' });
  await expect(navigation).toBeVisible();
  await expect(navigation.locator('.crm-public-sidebar-logo')).toBeVisible();
  await expect(navigation.getByRole('button', { name: 'Dark mode' })).toBeVisible();
  await expect(navigation.getByRole('button', { name: 'Light mode' })).toBeVisible();
  await expect(navigation.getByRole('button', { name: /new/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /applications/i })).toHaveCount(0);
  await expect(navigation.getByRole('button', { name: /workspace/i })).toHaveCount(0);
  await expect(page.locator('.crm-public-notice')).toHaveCount(0);
  await expect(page.getByRole('banner', { name: 'Mobile public navigation' })).not.toBeVisible();
  expect(await navigation.locator('.crm-public-sidebar-frame').evaluate((node) => getComputedStyle(node).borderRadius)).toBe('34px');
  const sidebarBounds = await navigation.locator('.crm-public-sidebar-frame').boundingBox();
  const workspaceBounds = await page.locator('.product-main').boundingBox();
  expect(sidebarBounds!.x).toBeGreaterThan(0);
  expect(workspaceBounds!.x).toBeGreaterThanOrEqual(sidebarBounds!.x + sidebarBounds!.width);

  await navigation.getByRole('button', { name: 'Light mode' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(navigation.getByRole('button', { name: 'Light mode' })).toHaveAttribute('aria-pressed', 'true');
  expect(await page.locator('body').evaluate((node) => getComputedStyle(node).backgroundColor)).toBe('rgb(247, 248, 251)');
  expect(await page.evaluate(() => localStorage.getItem('maverick:crm-public:theme'))).toBe('light');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.getByRole('button', { name: 'Light mode' })).toHaveAttribute('aria-pressed', 'true');

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileHeader = page.getByRole('banner', { name: 'Mobile public navigation' });
  const menu = page.getByRole('button', { name: 'Open navigation' });
  await expect(mobileHeader).toBeVisible();
  await expect(menu).toBeVisible();
  await expect(mobileHeader.getByAltText('Maverick')).toBeVisible();
  await expect(mobileHeader.getByRole('button', { name: 'App switching unavailable' })).toBeDisabled();
  await expect(mobileHeader.getByRole('button', { name: 'Create unavailable' })).toBeDisabled();
  await expect(mobileHeader.getByRole('button', { name: 'Chat unavailable' })).toBeDisabled();
  await expect(navigation).not.toBeVisible();
  const headerBounds = await mobileHeader.boundingBox();
  const topbarBounds = await page.locator('.crm-topbar').boundingBox();
  expect(topbarBounds!.y).toBeGreaterThanOrEqual(headerBounds!.y + headerBounds!.height);
  await page.screenshot({ path: testInfo.outputPath('crm-public-mobile-header.png'), fullPage: true });
  await menu.click();
  await expect(navigation).toBeVisible();
  await expect(navigation.locator('.crm-public-sidebar-logo')).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath('crm-public-mobile-navigation.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await navigation.getByRole('button', { name: 'People', exact: true }).click();
  await expect(navigation).not.toBeVisible();
  await expect(page.getByRole('heading', { name: 'People', exact: true })).toBeVisible();
});
