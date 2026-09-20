import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { chromium } from '@playwright/test';

const child = spawn('/usr/bin/python3', ['-B', new URL('./public_browser_fixture.py', import.meta.url).pathname], { stdio: ['ignore', 'pipe', 'inherit'] });
const reader = createInterface({ input: child.stdout });
let browser;
try {
  const [line] = await Promise.race([once(reader, 'line'), once(child, 'exit').then(() => { throw new Error('Fixture exited before readiness'); })]);
  const { url } = JSON.parse(line);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor();
  assert.match(await page.locator('.crm-public-notice').innerText(), /Sola lettura/);
  const sidebar = page.getByRole('navigation', { name: 'CRM workspace' });
  await sidebar.getByRole('button', { name: 'People', exact: true }).click();
  await page.getByRole('button', { name: 'Public Browser Contact', exact: true }).waitFor();
  const navigation = await page.locator('.crm-public-navigation').boundingBox();
  const canvas = await page.locator('.product-main').boundingBox();
  assert.ok(navigation.width >= 200 && canvas.x >= navigation.width, 'Standalone navigation must not overlap the canvas');
  await page.reload();
  await page.getByRole('button', { name: 'Public Browser Contact', exact: true }).waitFor();
  await sidebar.getByText('Workspace tools', { exact: true }).click();
  await sidebar.getByRole('button', { name: 'Records', exact: true }).click();
  await page.getByRole('heading', { name: 'CRM records' }).waitFor();
  await page.getByRole('textbox', { name: 'Search CRM' }).fill('Browser');
  await page.waitForTimeout(400);
  assert.equal(await page.locator('.crm-alert').count(), 0);
  const denied = await page.evaluate(async () => {
    const write = await fetch('/api/apps/crm/backend', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'crm.create_contact', display_name: 'Forbidden' }) });
    const privateRoute = await fetch('/api/apps/chat/backend');
    return [write.status, privateRoute.status];
  });
  assert.deepEqual(denied, [403, 404]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await sidebar.getByRole('button', { name: 'Dashboard', exact: true }).click();
  await page.getByRole('heading', { name: 'Dashboard', exact: true }).waitFor();
  assert.ok(await page.getByRole('button', { name: 'Open navigation', exact: true }).isVisible());
  assert.deepEqual(errors, []);
  console.log('PASS confined public CRM: real data, navigation, reload, search, mobile, denied writes/private routes');
} finally {
  await browser?.close();
  reader.close();
  if (child.exitCode === null) {
    const exited = once(child, 'exit');
    child.kill('SIGTERM');
    await exited;
  }
}
