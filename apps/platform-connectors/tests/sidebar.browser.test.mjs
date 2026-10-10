import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { chromium } from '../../base-shell/tests/shell-presentation-fixture.mjs';
import { browserExecutable, close } from '../../base-shell/tests/browser-contract-support.mjs';
import { sidebarFixture, sources } from './sidebar-fixture.mjs';

test('native shell hosts source navigation, preserves desktop sidebar and closes mobile selection', { timeout: 60_000 }, async () => {
  const fixture = await sidebarFixture();
  let browser;
  let inspectedPage;
  try {
    browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    await context.addInitScript(() => localStorage.setItem('maverick:base-shell:session', JSON.stringify({
      activeAppId: 'platform-connectors', sidebarMode: 'fixed', isSidebarOpen: true })));
    const page = await context.newPage();
    inspectedPage = page;
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(fixture.origin + '/app/platform-connectors?source=github');
    const sidebar = page.frameLocator('iframe[title="App sidebar content"]');
    const app = page.frameLocator('iframe.bs-workspace-app-frame');
    await sidebar.getByRole('button', { name: 'GitHub', exact: true }).waitFor();
    await app.getByRole('heading', { name: 'GitHub', exact: true }).waitFor();
    assert.equal(await sidebar.locator('.source-option').count(), 9);
    assert.equal(await app.locator('aside.sources, .source-option').count(), 0);
    assert.equal(await sidebar.getByRole('button', { name: 'GitHub', exact: true }).getAttribute('aria-pressed'), 'true');
    for (const source of sources) {
      await sidebar.getByRole('button', { name: source.name, exact: true }).click();
      await app.getByRole('heading', { name: source.name, exact: true }).waitFor();
      assert.equal(await page.locator('.bs-shell.is-sidebar-mode-fixed').count(), 1);
    }
    await app.getByRole('button', { name: 'History', exact: false }).click();
    await sidebar.getByRole('button', { name: 'Instagram', exact: true }).click();
    await app.getByRole('heading', { name: 'Instagram', exact: true }).waitFor();
    assert.equal(await app.getByRole('button', { name: 'Explore', exact: true }).getAttribute('aria-current'), 'page');
    await app.getByRole('button', { name: 'History', exact: false }).click();
    await page.waitForFunction(() => location.search.includes('tab=history'));
    await sidebar.getByRole('button', { name: 'Instagram', exact: true }).click();
    await app.getByRole('heading', { name: 'Instagram', exact: true }).waitFor();
    assert.equal(await app.getByRole('button', { name: 'Explore', exact: true }).getAttribute('aria-current'), 'page');
    await app.getByRole('button', { name: 'Read a feed →', exact: true }).click();
    await app.getByRole('heading', { name: 'RSS / Atom', exact: true }).waitFor();
    await page.waitForFunction(() => location.search.includes('source=rss'));
    await sidebar.locator('.source-option.selected').filter({ hasText: 'RSS / Atom' }).waitFor();
    assert.equal(await sidebar.getByRole('button', { name: 'RSS / Atom', exact: true }).getAttribute('aria-pressed'), 'true');

    // Untrusted frame-local messages cannot spoof shell navigation or selection.
    const widgetFrame = page.frames().find((frame) => frame.url().includes('connectors-sidebar'));
    await widgetFrame.evaluate(() => window.postMessage({ type: 'maverick.app.selection-changed', owner_app_id: 'platform-connectors', selection: { source: 'github' } }, location.origin));
    assert.equal(await sidebar.getByRole('button', { name: 'RSS / Atom', exact: true }).getAttribute('aria-pressed'), 'true');
    assert(await app.locator('body').evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await sidebar.getByRole('button', { name: 'GitHub', exact: true }).focus();
    assert(await sidebar.getByRole('button', { name: 'GitHub', exact: true }).evaluate((button) => button === document.activeElement));
    await sidebar.getByText('Your sign-in stays in Chrome.', { exact: false }).scrollIntoViewIfNeeded();
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ animations: 'disabled', path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, 'connectors-shell-desktop.png') });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.bs-mobile-shell-header__menu').waitFor();
    await sidebar.locator('.connectors-sidebar.is-shell-mobile').waitFor();
    if (!await page.locator('.bs-shell.is-sidebar-open').count())
      await page.locator('.bs-mobile-shell-header__menu').click();
    await page.locator('.bs-shell.is-sidebar-open').waitFor();
    await sidebar.getByRole('button', { name: 'Instagram', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.bs-shell.is-sidebar-open'));
    await app.getByRole('heading', { name: 'Instagram', exact: true }).waitFor();
    assert(await app.locator('body').evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ animations: 'disabled', path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, 'connectors-shell-mobile.png') });
    await page.locator('.bs-mobile-shell-header__menu').click();
    await page.locator('.bs-shell.is-sidebar-open').waitFor();
    await sidebar.getByRole('button', { name: 'GitHub', exact: true }).scrollIntoViewIfNeeded();
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ animations: 'disabled', path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, 'connectors-shell-mobile-sidebar.png') });
    assert.equal(errors.length, 0, errors.join('\n'));
    assert(fixture.catalogRequests.length > 0);
    await context.close();
  } catch (error) {
    if (inspectedPage && !inspectedPage.isClosed()) {
      console.error('Sidebar fixture state:', await inspectedPage.locator('body').innerText());
      for (const frame of inspectedPage.frames()) {
        if (frame !== inspectedPage.mainFrame()) console.error(frame.url(), await frame.locator('body').innerText().catch(() => 'unavailable'));
      }
    }
    throw error;
  } finally {
    await browser?.close();
    await Promise.all([close(fixture.shell), close(fixture.frames)]);
  }
});
