import { expect, test } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { backend } from './backend_fixture';
import { mountSidebarHost } from './sidebar_host_fixture';

let dataRoot: string;
test.beforeEach(() => { dataRoot = mkdtempSync(`${tmpdir()}/crm-sidebar-e2e-`); });
test.afterEach(() => { rmSync(dataRoot, { recursive: true, force: true }); });

test('compact sidebar lives only in the shell widget and navigates the full-width canvas', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  backend(dataRoot, { action: 'crm.create_lead', id: 'lead_calogera', display_name: 'Calogera Carlisi', email: 'calogera@example.test' });
  backend(dataRoot, { action: 'crm.create_lead', id: 'lead_giuseppe', display_name: 'Giuseppe Moriggi', email: 'giuseppe@example.test' });
  const { widget, canvas } = await mountSidebarHost(page, dataRoot);
  const dashboard = widget.getByRole('button', { name: 'Dashboard', exact: true });
  await expect(widget.getByText('Relationship workspace', { exact: true })).toBeVisible();
  await expect(widget.locator('.product-sidebar footer')).toHaveCount(0);
  await expect(dashboard).toHaveAttribute('aria-current', 'page');
  await expect(widget.getByRole('button', { name: 'People', exact: true }).locator('small')).toHaveText('1');
  await expect(widget.getByRole('button', { name: 'Leads', exact: true }).locator('small')).toHaveText('2');
  await expect(canvas.getByRole('navigation', { name: 'CRM workspace' })).toHaveCount(0);
  await expect(canvas.getByRole('button', { name: 'Open navigation', exact: true })).toHaveCount(0);
  const widths = await canvas.locator('.product-main').evaluate((node) => ({ content: node.getBoundingClientRect().width, frame: innerWidth }));
  expect(widths.content).toBe(widths.frame);
  expect(await dashboard.evaluate((node) => getComputedStyle(node).borderRadius)).toBe('9px');
  expect(await dashboard.locator('svg').evaluate((node) => getComputedStyle(node).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  await expect(widget.getByRole('button', { name: 'Records', exact: true })).not.toBeVisible();
  await widget.getByRole('button', { name: 'Leads', exact: true }).click();
  await expect(widget.getByRole('button', { name: 'Leads', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(canvas.getByRole('heading', { name: 'CRM records' })).toBeVisible();
  await expect(canvas.getByRole('row').filter({ hasText: 'Calogera Carlisi' })).toBeVisible();
  await expect(canvas.getByRole('row').filter({ hasText: 'Giuseppe Moriggi' })).toBeVisible();
  await widget.getByRole('button', { name: 'People', exact: true }).click();
  await expect(canvas.getByRole('heading', { name: 'People', exact: true })).toBeVisible();
  await expect(widget.getByRole('button', { name: 'People', exact: true })).toHaveAttribute('aria-current', 'page');
  await dashboard.click();
  // In-canvas navigation must also update the only remaining sidebar.
  await canvas.locator('.product-card').filter({ has: canvas.getByRole('heading', { name: 'Latest people', exact: true }) }).getByRole('button', { name: 'View all', exact: true }).click();
  await expect(widget.getByRole('button', { name: 'People', exact: true })).toHaveAttribute('aria-current', 'page');
  await widget.getByText('Workspace tools', { exact: true }).click();
  await widget.getByRole('button', { name: 'Records', exact: true }).click();
  await expect(canvas.getByRole('heading', { name: 'CRM records' })).toBeVisible();
  await page.evaluate(() => (window as any).navigateCrm({ app_page: 'contacts/contact_ada' }));
  await expect(canvas.getByRole('complementary', { name: 'Record inspector' })).toBeVisible();
  await expect(widget.getByRole('button', { name: 'Records', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(widget.locator('details')).toHaveAttribute('open', '');
  expect(await page.evaluate(() => (window as any).navigationRequests.length)).toBeLessThan(8);
  await canvas.getByRole('button', { name: 'Back', exact: true }).click();
  await dashboard.click();
  await page.screenshot({ path: testInfo.outputPath('crm-single-sidebar-desktop.png'), fullPage: true });
});

test('trusted cross-origin context wins over late bootstrap; sibling messages cannot change navigation or counts', async ({ page }) => {
  const { widget, canvas, appOrigin, shellOrigin } = await mountSidebarHost(page, dataRoot, { delayedContext: true });
  await page.evaluate(() => (window as any).navigateCrm({ app_page: 'briefs/brief_missing' }));
  await expect(widget.getByRole('button', { name: 'Brief archive', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.waitForTimeout(1600);
  await expect(widget.getByRole('button', { name: 'Brief archive', exact: true })).toHaveAttribute('aria-current', 'page');
  // A real sibling shares the app origin but is not the exact shell parent.
  await canvas.locator('body').evaluate((_, origin) => {
    const target = window.parent.frames[0];
    target.postMessage({ type: 'maverick.widget.context-changed', context: { content: { payload: { active_app_params: { app_page: 'expenses' } } } } }, origin);
    target.postMessage({ type: 'maverick.widget.data-changed', owner_app_id: 'crm' }, origin);
  }, appOrigin);
  // Even an event with the correct claimed origin needs the actual parent source.
  await widget.locator('body').evaluate((_, origin) => window.dispatchEvent(new MessageEvent('message', {
    origin, source: window, data: { type: 'maverick.widget.context-changed', context: { content: { payload: { active_app_params: { app_page: 'expenses' } } } } },
  })), shellOrigin);
  await expect(widget.getByRole('button', { name: 'Brief archive', exact: true })).toHaveAttribute('aria-current', 'page');
  backend(dataRoot, { action: 'crm.create_contact', display_name: 'Second Person' });
  await page.evaluate(() => (window as any).refreshCounts());
  await expect(widget.getByRole('button', { name: 'People', exact: true }).locator('small')).toHaveText('2');
});

test('mobile shell owns the drawer; compact tools remain reachable and the canvas has no second menu', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 640 });
  const { widget, canvas } = await mountSidebarHost(page, dataRoot);
  await page.getByRole('button', { name: 'Open shell sidebar' }).click();
  await expect(widget.locator('.crm-sidebar-widget')).toHaveClass(/is-shell-mobile/);
  await expect(canvas.getByRole('button', { name: 'Open navigation', exact: true })).toHaveCount(0);
  await widget.getByText('Workspace tools', { exact: true }).click();
  const connections = widget.getByRole('button', { name: 'Connections', exact: true });
  await connections.scrollIntoViewIfNeeded();
  await expect(connections).toBeInViewport();
  await connections.click();
  await expect(canvas.getByRole('heading', { name: 'Apps & connections', exact: true })).toBeVisible();
  await expect(page.locator('#sidebar-frame')).not.toBeVisible();
  await page.getByRole('button', { name: 'Open shell sidebar' }).click();
  await widget.getByRole('button', { name: 'Dashboard', exact: true }).click();
  await expect(canvas.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  const bounds = await canvas.locator('.product-main').evaluate((node) => ({ left: node.getBoundingClientRect().left, width: node.getBoundingClientRect().width, frame: innerWidth, overflow: document.documentElement.scrollWidth }));
  expect(bounds.left).toBe(0);
  expect(bounds.width).toBe(bounds.frame);
  expect(bounds.overflow).toBe(bounds.frame);
  await page.getByRole('button', { name: 'Open shell sidebar' }).click();
  await page.screenshot({ path: testInfo.outputPath('crm-single-sidebar-mobile.png'), fullPage: true });
});

test('count failures do not invent zeros or block navigation, and retry recovers', async ({ page }) => {
  let failCounts = true;
  const { widget, canvas } = await mountSidebarHost(page, dataRoot, { failCounts: () => failCounts });
  await expect(widget.getByRole('status')).toContainText('Counts unavailable');
  await expect(widget.getByRole('button', { name: 'People', exact: true }).locator('small')).toHaveCount(0);
  await widget.getByRole('button', { name: 'People', exact: true }).click();
  await expect(canvas.getByRole('heading', { name: 'People', exact: true })).toBeVisible();
  failCounts = false;
  await widget.getByRole('button', { name: 'Retry counts' }).click();
  await expect(widget.getByRole('button', { name: 'People', exact: true }).locator('small')).toHaveText('1');
  await expect(widget.getByRole('status')).toHaveCount(0);
});

test('reflected report navigation preserves the inspector and a later route revisit still navigates', async ({ page }) => {
  backend(dataRoot, { action: 'crm.create_deal', id: 'deal_review', name: 'Review opportunity', value: 1200, currency: 'EUR' });
  const { widget, canvas } = await mountSidebarHost(page, dataRoot);
  await widget.getByText('Workspace tools', { exact: true }).click();
  await widget.getByRole('button', { name: 'Reports', exact: true }).click();
  await canvas.getByRole('button', { name: /Review opportunity/ }).click();
  await expect(widget.getByRole('button', { name: 'Records', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(canvas.getByRole('complementary', { name: 'Record inspector' })).toBeVisible();
  await expect(canvas.getByRole('region', { name: 'Review opportunity', exact: true })).toBeVisible();
  const reflectedRoute = await page.evaluate(() => (window as any).navigationRequests.findLast((request: any) => request.params?.crm_navigation_id)?.params);
  expect(reflectedRoute?.app_page).toBe('records');
  await widget.getByRole('button', { name: 'Dashboard', exact: true }).click();
  await page.evaluate((params) => (window as any).navigateCrm(params), reflectedRoute);
  await expect(canvas.getByRole('heading', { name: 'CRM records', exact: true })).toBeVisible();
  await expect(canvas.getByRole('complementary', { name: 'Record inspector' })).toHaveCount(0);
});
