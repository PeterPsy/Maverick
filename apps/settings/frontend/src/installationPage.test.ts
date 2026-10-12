// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { mountInstallation } from '../../../../packages/installation-ui/src/view';
import { clearSettingsDomCache, patchSettingsDom } from './settingsDom';

const inspection = { configuration: { hostname: 'maverick.example.com', public_url: 'https://maverick.example.com', target_ip: '8.8.8.8', generation: 0, managed: true },
  dns_credentials: [{ label: 'Cloudflare DNS', ref: 'platform:secrets/token' }], requirements: [], configured: true,
  worker: { state: 'healthy', public_ip: '8.8.8.8', checked_at: new Date().toISOString() } };
let root: HTMLElement;
let view: ReturnType<typeof mountInstallation> | undefined;
beforeEach(() => {
  clearSettingsDomCache(); document.body.innerHTML = '<div id="app"></div>'; root = document.getElementById('app')!;
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(inspection), { status: 200 })));
});
afterEach(() => { view?.destroy(); view = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('keeps the installation island and address draft during unrelated Settings renders', async () => {
  const html = '<section><div id="installation-root" data-settings-owned-view="installation"></div></section>';
  patchSettingsDom(root, html);
  const island = root.querySelector<HTMLElement>('#installation-root')!;
  view = mountInstallation(island);
  await vi.waitFor(() => expect(island.querySelector<HTMLInputElement>('[name=address]')!.value).toBe('maverick.example.com'));
  const input = island.querySelector<HTMLInputElement>('[name=address]')!;
  input.value = 'new.example.com'; input.focus(); input.dispatchEvent(new Event('input', { bubbles: true }));
  patchSettingsDom(root, html);
  expect(island.querySelector('[name=address]')).toBe(input);
  expect(input.value).toBe('new.example.com'); expect(document.activeElement).toBe(input);
});

it('clears the credential input and cancels requests when leaving setup', () => {
  view = mountInstallation(root);
  const token = root.querySelector<HTMLInputElement>('[data-installation-token]')!;
  token.value = 'private-test-token';
  view.destroy(); view = undefined;
  expect(token.value).toBe(''); expect(root.children).toHaveLength(0);
});

it('sends a pasted credential only to Core Secrets and keeps its value out of the view and browser storage', async () => {
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation(async (url) => new Response(JSON.stringify(String(url) === '/api/secrets' ? { secret: { secret_id: 'saved-token' } } : inspection), { status: 200 }));
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  view = mountInstallation(root);
  await vi.waitFor(() => expect(root.querySelector('[data-installation-overview]')?.textContent).toContain('maverick.example.com'));
  root.querySelector<HTMLInputElement>('[data-installation-token]')!.value = 'private-test-token';
  root.querySelector<HTMLButtonElement>('[data-installation-action=save-token]')!.click();
  await vi.waitFor(() => expect(root.querySelector<HTMLInputElement>('[data-installation-token]')!.value).toBe(''));
  const secretCall = fetchMock.mock.calls.find(([url]) => url === '/api/secrets')!;
  expect(JSON.parse(String(secretCall[1]?.body)).raw_value).toBe('private-test-token');
  expect(root.innerHTML).not.toContain('private-test-token'); expect(storage).not.toHaveBeenCalled();
});
