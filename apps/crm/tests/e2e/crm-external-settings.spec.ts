import { expect, Page, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

const widgetUrl = '/apps/crm/widgets/crm-external-settings/index.html';
const initial = { configured: true, enabled: true, ready: true, url: 'https://crm.apps.example.test', access: 'read-only', revision: 7 };
const consent = 'Ho verificato e confermo questa configurazione.';

async function mockBackend(page: Page, options: { status?: Partial<typeof initial>; loadError?: boolean; saveError?: boolean } = {}) {
  let state = { ...initial, ...options.status };
  const writes: Record<string, unknown>[] = [];
  let reads = 0;
  await page.route('**/api/apps/crm/backend', async route => {
    const body = route.request().postDataJSON();
    if (body.action === 'crm.external.status') {
      reads += 1;
      if (options.loadError && reads === 1) return route.fulfill({ status: 503, json: { message: 'Servizio temporaneamente non disponibile.' } });
    } else if (body.action === 'crm.external.configure') {
      writes.push(body);
      if (options.saveError) return route.fulfill({ status: 409, json: { message: 'Configurazione cambiata. Aggiorna lo stato.' } });
      state = { ...state, enabled: body.enabled, access: body.access, revision: state.revision + 1, ready: false };
    } else throw new Error(`Unexpected settings action: ${body.action}`);
    await route.fulfill({ json: state });
  });
  return { writes, reads: () => reads };
}

test('saved state is compact, copyable and never writes without a change', async ({ page }) => {
  const backend = await mockBackend(page);
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (value: string) => { (window as any).copied = value; } } }));
  await page.goto(widgetUrl);
  await expect(page.getByText('Servizio attivo', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Apri CRM' })).toHaveAttribute('href', initial.url);
  await expect(page.getByRole('switch')).toBeChecked();
  await expect(page.getByRole('radio', { name: /Sola lettura/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: consent })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Salva modifiche' })).toBeDisabled();
  await page.getByRole('button', { name: 'Copia link' }).click();
  await expect(page.getByText('Link copiato', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as any).copied)).toBe(initial.url);
  await page.getByRole('button', { name: 'Aggiorna stato' }).click();
  await expect.poll(backend.reads).toBe(2);
  expect(backend.writes).toEqual([]);
});

test('edits require fresh consent, cannot be overwritten by refresh and can be cancelled', async ({ page }) => {
  const backend = await mockBackend(page);
  await page.goto(widgetUrl);
  const save = page.getByRole('button', { name: 'Salva modifiche' });
  await page.getByRole('radio', { name: /Lettura e scrittura/ }).check();
  await expect(page.getByText(/Senza login:.*cancellare/)).toBeVisible();
  await expect(save).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Aggiorna stato' })).toBeDisabled();
  await page.getByRole('checkbox', { name: consent }).check();
  await expect(save).toBeEnabled();
  await page.getByRole('switch').uncheck();
  await expect(page.getByRole('checkbox', { name: consent })).not.toBeChecked();
  await expect(save).toBeDisabled();
  // Badge describes the saved service, not the unsaved draft.
  await expect(page.getByText('Servizio attivo', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Annulla', exact: true }).click();
  await expect(page.getByRole('switch')).toBeChecked();
  await expect(page.getByRole('radio', { name: /Sola lettura/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: consent })).toHaveCount(0);
  expect(backend.writes).toEqual([]);
});

test('explicit save uses the saved revision and subsequent saves use the returned revision', async ({ page }) => {
  const backend = await mockBackend(page);
  await page.goto(widgetUrl);
  await page.getByRole('radio', { name: /Lettura e scrittura/ }).check();
  await page.getByRole('checkbox', { name: consent }).check();
  await page.getByRole('button', { name: 'Salva modifiche' }).click();
  await expect(page.getByText('Configurazione salvata', { exact: true })).toBeVisible();
  await expect(page.getByText('In attesa del servizio', { exact: true })).toBeVisible();
  expect(backend.writes).toEqual([{ action: 'crm.external.configure', enabled: true, access: 'read-write', expected_revision: 7, confirm: true }]);
  await expect(page.getByRole('button', { name: 'Salva modifiche' })).toBeDisabled();
  await page.getByRole('switch').uncheck();
  await page.getByRole('checkbox', { name: consent }).check();
  await page.getByRole('button', { name: 'Salva modifiche' }).click();
  await expect(page.getByText('Disattivato', { exact: true })).toBeVisible();
  expect(backend.writes[1]).toEqual({ action: 'crm.external.configure', enabled: false, access: 'read-write', expected_revision: 8, confirm: true });
  await expect(page.getByRole('link', { name: 'Apri CRM' })).toHaveCount(0);
});

test('saving locks draft controls until the response arrives', async ({ page }) => {
  await mockBackend(page);
  let release: (() => Promise<void>) | undefined;
  await page.route('**/api/apps/crm/backend', route => {
    if (route.request().postDataJSON().action !== 'crm.external.configure') return route.fallback();
    release = () => route.fulfill({ json: { ...initial, access: 'read-write', revision: 8 } });
  });
  await page.goto(widgetUrl);
  await page.getByRole('radio', { name: /Lettura e scrittura/ }).check();
  await page.getByRole('checkbox', { name: consent }).check();
  await page.getByRole('button', { name: 'Salva modifiche' }).click();
  await expect(page.getByRole('button', { name: 'Salvataggio…' })).toBeDisabled();
  await expect(page.getByRole('switch')).toBeDisabled();
  await expect(page.getByRole('radio', { name: /Sola lettura/ })).toBeDisabled();
  await expect(page.getByRole('checkbox', { name: consent })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Annulla', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Aggiorna stato' })).toBeDisabled();
  await expect.poll(() => Boolean(release)).toBe(true);
  await release!();
  await expect(page.getByText('Configurazione salvata', { exact: true })).toBeVisible();
});

test('save errors preserve the draft, revoke consent and never automatically replay', async ({ page }) => {
  const backend = await mockBackend(page, { saveError: true });
  await page.goto(widgetUrl);
  await page.getByRole('radio', { name: /Lettura e scrittura/ }).check();
  await page.getByRole('checkbox', { name: consent }).check();
  await page.getByRole('button', { name: 'Salva modifiche' }).click();
  await expect(page.getByRole('alert')).toContainText('Configurazione cambiata');
  await expect(page.getByRole('radio', { name: /Lettura e scrittura/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: consent })).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'Salva modifiche' })).toBeDisabled();
  expect(backend.writes).toHaveLength(1);
  await page.getByRole('button', { name: 'Annulla', exact: true }).click();
  await page.getByRole('button', { name: 'Aggiorna stato' }).click();
  await expect.poll(backend.reads).toBe(2);
});

test('failed initial load exposes retry instead of an endless spinner', async ({ page }) => {
  const backend = await mockBackend(page, { loadError: true });
  await page.goto(widgetUrl);
  await expect(page.getByRole('alert')).toContainText('Servizio temporaneamente non disponibile');
  await expect(page.getByText('Caricamento impostazioni…')).toHaveCount(0);
  await page.getByRole('button', { name: 'Aggiorna stato' }).click();
  await expect(page.getByRole('switch')).toBeChecked();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(backend.writes).toEqual([]);
});

test('unconfigured hosting is honest and cannot be enabled', async ({ page }) => {
  await mockBackend(page, { status: { configured: false, enabled: false, ready: false, url: '' } });
  await page.goto(widgetUrl);
  await expect(page.getByText('Da configurare', { exact: true })).toBeVisible();
  await expect(page.getByText('Dominio non configurato', { exact: true })).toBeVisible();
  await expect(page.getByRole('switch')).toBeDisabled();
  await expect(page.getByRole('radio', { name: /Sola lettura/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Copia link' })).toHaveCount(0);
});

for (const viewport of [{ width: 1000, height: 650 }, { width: 390, height: 600 }]) {
  test(`shell iframe keeps save reachable without horizontal overflow at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await mockBackend(page, { status: { url: `https://crm.apps.${'long-installation-domain-'.repeat(3)}example.test` } });
    const shellCss = ['app-settings.css', 'sidebar.css'].map(name => readFileSync(new URL(`../../../base-shell/frontend/src/styles/${name}`, import.meta.url), 'utf8')).join('\n');
    const appOrigin = `http://127.0.0.1:${process.env.CRM_PLAYWRIGHT_PORT || '5187'}`;
    const shellOrigin = appOrigin.replace('127.0.0.1', 'localhost');
    await page.context().grantPermissions(['local-network-access'], { origin: shellOrigin });
    await page.addInitScript(({ appOrigin, shellOrigin }) => {
      if (location.origin === appOrigin) (window as any).__MAVERICK_PLATFORM_ORIGIN__ = shellOrigin;
    }, { appOrigin, shellOrigin });
    await page.route('**/__settings_host', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><style>
      * { box-sizing: border-box; } :root { --maverick-bg:#070708; --maverick-text:#ececec; --maverick-text-muted:#aaa; --maverick-border:#ffffff14; --maverick-border-strong:#ffffff24; --maverick-surface-active:#ffffff24; --bs-mobile-shell-status-bar-height:${viewport.width === 390 ? '24px' : '0px'}; font:14px system-ui; } body { margin:0; background:#111; } ${shellCss}
      </style></head><body><dialog class="bs-app-settings"><header class="bs-app-settings__header"><div><p>Impostazioni app</p><h2>CRM</h2></div><button class="bs-app-settings__close">×</button></header>
      <nav class="bs-app-settings__tabs"><button>Generali</button><button aria-pressed="true">Superfici esterne</button></nav>
      <div class="bs-app-settings__body bs-app-settings__body--external"><section class="bs-widget-slot bs-widget-slot--fill"><iframe class="bs-widget-slot__frame" title="CRM settings" allow="fullscreen" sandbox="allow-downloads allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts" src="${appOrigin}${widgetUrl}"></iframe></section></div></dialog><script>document.querySelector('dialog').showModal();</script></body></html>` }));
    await page.goto(`${shellOrigin}/__settings_host`);
    const widget = page.frameLocator('iframe');
    const save = widget.getByRole('button', { name: 'Salva modifiche' });
    await expect(save).toBeInViewport({ ratio: 1 });
    await widget.getByRole('radio', { name: /Lettura e scrittura/ }).check();
    await expect(widget.getByRole('checkbox', { name: consent })).toBeInViewport({ ratio: 1 });
    await widget.getByRole('checkbox', { name: consent }).check();
    await expect(save).toBeInViewport({ ratio: 1 });
    const bounds = await widget.locator('body').evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth, height: innerHeight, scrollHeight: document.documentElement.scrollHeight }));
    expect(bounds.scroll).toBe(bounds.width);
    expect(bounds.scrollHeight).toBe(bounds.height);
    if (viewport.width === 390) {
      const dialog = await page.locator('.bs-app-settings').boundingBox();
      expect(dialog).toEqual({ x: 6, y: 34, width: 378, height: 556 });
    }
    await widget.locator('.crm-external-content').evaluate(node => { node.scrollTop = 0; });
    await expect(save).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: testInfo.outputPath('crm-settings-dark.png') });
    await page.evaluate(origin => document.querySelector('iframe')!.contentWindow!.postMessage({ type: 'maverick.widget.context-changed', context: { content: { shell_theme: { effective: 'light' } } } }, origin), appOrigin);
    await expect(widget.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await widget.locator('html').evaluate(node => getComputedStyle(node).colorScheme)).toBe('light');
    await page.screenshot({ path: testInfo.outputPath('crm-settings-light.png') });
    await widget.locator('body').evaluate(() => document.addEventListener('copy', () => { (window as any).copyEventSeen = true; }));
    await widget.getByRole('button', { name: 'Copia link' }).click();
    await expect(widget.getByText('Link copiato', { exact: true })).toBeVisible();
    expect(await widget.locator('body').evaluate(() => (window as any).copyEventSeen)).toBe(true);
    await expect(widget.getByRole('button', { name: 'Copia link' })).toBeFocused();
    await expect(widget.locator('textarea')).toHaveCount(0);
  });
}
