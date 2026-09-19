import { expect, test } from '@playwright/test';

const release = { release_id: 'rel_' + 'a'.repeat(32), digest: 'b'.repeat(64), size_bytes: 300, file_count: 2, format: 'static_bundle' };
const publication = { id: 'app_1', name: 'Demo sintetica', managed_url: 'https://demo.example.test', provider_id: 'website-studio', source_id: 'site_demo', status: 'draft', last_error_code: '', health: { status: 'unknown' }, binding: { generation: 0, enabled: false, archived: false } };
const plan = { id: 'plan_1', app_id: 'app_1', kind: 'publish', status: 'ready', hostname: 'demo.example.test', source_revision: 'revision_1', plan_digest: 'c'.repeat(64), expires: Date.now() / 1000 + 900, release };

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`human approval, responsive layout and cancellation ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    let app: any = structuredClone(publication);
    let plans: any[] = [structuredClone(plan)];
    const actions: string[] = [];
    await page.route('**/api/apps/external-apps/backend', async route => {
      const body = route.request().postDataJSON();
      actions.push(body.action);
      let result: object;
      if (body.action === 'list') result = { items: [app] };
      else if (body.action === 'health') result = { status: 'configured' };
      else if (body.action === 'get') result = { app, plans, releases: [], history: [] };
      else if (body.action === 'plan.approve') result = { plan: { ...plan, approved_by: 'human' } };
      else if (body.action === 'publish.apply') {
        app = { ...app, status: 'published', binding: { ...app.binding, enabled: true, generation: 1, current: release } };
        plans = [{ ...plan, status: 'applied' }];
        result = { status: 'published' };
      } else result = { error_code: 'unexpected_test_action' };
      await route.fulfill({ json: result });
    });
    await page.goto('/apps/external-apps/');
    await page.getByRole('button', { name: /Demo sintetica/ }).click();
    await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.reject(new Error('frame policy')) }, configurable: true }));
    await page.getByRole('button', { name: 'Copia URL' }).click();
    await expect(page.getByRole('button', { name: 'URL copiato' })).toBeVisible();
    const approve = page.getByRole('button', { name: 'Approva e pubblica' });
    await expect(approve).toBeDisabled();
    await expect(page.getByText('SHA-256:', { exact: false })).toContainText(release.digest);
    await page.getByRole('checkbox').check();
    await approve.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('status')).toContainText('Pubblicata');
    expect(actions.indexOf('plan.approve')).toBeLessThan(actions.indexOf('publish.apply'));
    await page.getByRole('button', { name: 'Sospendi', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).not.toBeVisible();
    expect(actions).not.toContain('suspend');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  });
}

test('safe backend errors and honest deployment setup', async ({ page }) => {
  await page.route('**/api/apps/external-apps/backend', route => route.fulfill({ json: route.request().postDataJSON().action === 'list' ? { items: [] } : { status: 'not_configured' } }));
  await page.goto('/apps/external-apps/');
  await expect(page.getByRole('heading', { name: 'Configurazione richiesta' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Prepara pubblicazione' })).toBeDisabled();
  await page.unroute('**/api/apps/external-apps/backend');
  await page.route('**/api/apps/external-apps/backend', route => route.fulfill({ status: 403, json: { error_code: 'admin_required' } }));
  await page.getByLabel('Dominio pubblico').fill('apps.example.test');
  await page.getByRole('button', { name: 'Salva dominio' }).click();
  await expect(page.getByRole('alert')).toHaveText('admin_required');
});

test('Core frame identity, exact-parent theme and navigation reset', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(window, '__MAVERICK_APP_FRAME_CONTEXT__', { value: { app_id: 'publisher', workspace_id: 'synthetic' }, writable: false }));
  await page.route('**/api/apps/publisher/backend', route => {
    const action = route.request().postDataJSON().action;
    return route.fulfill({ json: action === 'list' ? { items: [publication] } : action === 'get' ? { app: publication, plans: [plan], releases: [], history: [] } : { status: 'configured' } });
  });
  await page.goto('/apps/external-apps/?maverick_theme=dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: /Demo sintetica/ }).click();
  await page.getByRole('checkbox').check();
  await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { source: window, origin: 'https://wrong.example', data: { type: 'maverick.shell.theme-changed', theme: { effective: 'light' } } })));
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.evaluate(() => window.postMessage({ type: 'maverick.shell.theme-changed', theme: { effective: 'light' } }, location.origin));
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.evaluate(() => window.postMessage({ type: 'maverick.app.navigate', app_id: 'publisher', params: {} }, location.origin));
  await expect(page.getByRole('article', { name: 'Dettaglio pubblicazione' })).toHaveCount(0);
  await page.getByRole('button', { name: /Demo sintetica/ }).click();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
});
