import { expect, test } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { mount, navigate } from './backend_fixture';

test('hidden CRM cancels display reads, ignores late values and resumes once without losing rows', async ({ page }) => {
  const root = mkdtempSync(`${tmpdir()}/crm-visibility-`);
  let release = () => {};
  try {
    await mount(page, root);
    await navigate(page, 'People');
    const ada = page.getByRole('button', { name: 'Ada Example', exact: true });
    await expect(ada).toBeVisible();
    let held = 0;
    const waiting = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/api/apps/crm/backend', async route => {
      const body = route.request().postDataJSON();
      if (body.action === 'pwa.read_model' && body.kind === 'records_table' && body.entity_type === 'contact' && held === 0) {
        held++;
        await waiting;
        await route.fulfill({ status: 503, json: { message: 'Obsolete hidden request' } }).catch(() => {});
      } else await route.fallback();
    });
    await page.getByRole('button', { name: 'Refresh view', exact: true }).click();
    await expect.poll(() => held).toBe(1);
    const visibility = (visible: boolean) => page.evaluate(visible => window.postMessage({
      type: 'maverick.app.visibility-changed', visible,
    }, window.location.origin), visible);
    await visibility(false);
    await page.waitForTimeout(100);
    const reads: Record<string, unknown>[] = [];
    page.on('request', request => {
      if (request.url().endsWith('/api/apps/crm/backend')) reads.push(request.postDataJSON());
    });
    await page.evaluate(() => window.dispatchEvent(new Event('crm-workspace-refresh')));
    await page.context().setOffline(true);
    await page.context().setOffline(false);
    release();
    await page.waitForTimeout(1_100);
    expect(reads).toHaveLength(0);
    await expect(ada).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await visibility(true);
    await expect.poll(() => reads.filter(body => body.action === 'pwa.read_model' && body.kind === 'records_table' && body.entity_type === 'contact').length).toBe(1);
    await expect(ada).toBeVisible();
    await page.waitForTimeout(300);
    expect(reads.filter(body => body.action === 'pwa.read_model' && body.kind === 'records_table' && body.entity_type === 'contact')).toHaveLength(1);
  } finally {
    release();
    await page.close();
    rmSync(root, { recursive: true, force: true });
  }
});
