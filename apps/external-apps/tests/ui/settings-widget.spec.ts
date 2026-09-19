import { expect, test } from '@playwright/test';

for (const width of [860, 340]) {
  test(`per-app widget keeps source scope, consent and parent identity isolated ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 });
    await page.addInitScript(() => Object.defineProperty(window, '__MAVERICK_APP_FRAME_CONTEXT__', { value: { app_id: 'publisher', workspace_id: 'synthetic' }, writable: false }));
    const calls: Record<string, unknown>[] = [];
    const release = { release_id: 'rel_' + 'a'.repeat(32), digest: 'b'.repeat(64), size_bytes: 300, file_count: 2, format: 'static_bundle' };
    const app = { id: 'app_a', name: 'Sito A', managed_url: 'https://site-a.apps.example.test', provider_id: 'website-studio', source_id: 'site_a', status: 'draft', last_error_code: '', health: { status: 'unknown' }, binding: { generation: 0, enabled: false, archived: false } };
    const plan = { id: 'plan_a', app_id: 'app_a', kind: 'publish', status: 'ready', hostname: 'site-a.apps.example.test', source_revision: 'revision_a', plan_digest: 'c'.repeat(64), expires: Date.now() / 1000 + 900, release };
    await page.route('**/api/apps/publisher/backend', route => {
      const body = route.request().postDataJSON(); calls.push(body);
      return route.fulfill({ json: body.action === 'health' ? { status: 'configured', selected_exporter_app_id: 'website-studio' }
        : body.action === 'list' ? { items: body.source_app_id === 'website-studio' ? [app] : [] }
        : body.action === 'get' ? { app, plans: [plan], releases: [], history: [] }
        : body.action === 'plan.approve' ? { plan: { ...plan, approved_by: 'human' } } : { status: 'published' } });
    });
    await page.goto('/widgets/external-surfaces-settings/?maverick_theme=dark');
    await expect(page.getByRole('status')).toHaveText('Caricamento del contesto app…');
    expect(calls).toHaveLength(0);
    async function context(id: string, owner = 'publisher', origin?: string) {
      await page.evaluate(({ id, owner, origin }) => {
        const data = { type: 'maverick.widget.context-changed', owner_app_id: owner, widget_id: 'external-surfaces-settings', context: { content: { kind: 'shell.app.external.surfaces', payload: { app_id: id, app_name: id }, shell_theme: { effective: 'dark' } } } };
        if (origin) window.dispatchEvent(new MessageEvent('message', { source: window, origin, data }));
        else window.postMessage(data, location.origin);
      }, { id, owner, origin });
    }
    await context('website-studio', 'foreign');
    await context('website-studio', 'publisher', 'https://foreign.invalid');
    await expect(page.getByRole('status')).toHaveText('Caricamento del contesto app…');
    expect(calls).toHaveLength(0);
    await context('website-studio');
    await expect(page.getByRole('heading', { name: 'Superfici esterne' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByRole('button', { name: 'Prepara pubblicazione' })).toBeEnabled();
    await page.getByRole('button', { name: /Sito A/ }).click();
    await page.getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Approva e pubblica' }).click();
    await expect(page.getByRole('status')).toContainText('Pubblicata');
    expect(calls.filter(call => call.action !== 'health').every(call => call.source_app_id === 'website-studio')).toBe(true);
    expect(calls.some(call => call.action === 'plan.approve')).toBe(true);
    expect(calls.some(call => call.action === 'publish.apply')).toBe(true);
    await context('chat');
    await expect(page.getByRole('button', { name: 'Prepara pubblicazione' })).toBeDisabled();
    await expect(page.getByText('Nessuna UI o API privata viene resa pubblica.', { exact: false })).toBeVisible();
    await expect(page.getByRole('article', { name: 'Dettaglio pubblicazione' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Sito A/ })).toHaveCount(0);
    await expect(page.getByLabel('Dominio di Maverick')).toHaveCount(0);
    await context('website-studio');
    await page.getByRole('button', { name: /Sito A/ }).click();
    await expect(page.getByRole('checkbox')).not.toBeChecked();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  });
}
