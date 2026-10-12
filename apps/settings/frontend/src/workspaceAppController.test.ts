// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest';
import { setWorkspaceAppEnabled } from './adminActions';
import type { WorkspaceApp } from './adminApi';
import { createWorkspaceAppController } from './workspaceAppController';
import { workspaceAppsPageHtml } from './workspaceAppsPage';
import { clearSettingsDomCache, patchSettingsDom, rememberSettingsDrafts } from './settingsDom';
import { beginSettingsBindings, bindControl } from './controlBindings';

vi.mock('./adminActions', () => ({ setWorkspaceAppEnabled: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks(); clearSettingsDomCache(); document.body.innerHTML = '<div id="app"></div>';
  rememberSettingsDrafts(document.getElementById('app')!);
});

const app: WorkspaceApp = { workspace_id: 'default', workspace_name: 'Default', app_id: 'test', name: 'Test', description: '', version: '1', source_id: 'test', installed: true, status: 'disabled' };

function mount() {
  let apps = [app]; let saving: Promise<void>;
  const render = () => {
    patchSettingsDom(document.getElementById('app')!, workspaceAppsPageHtml({
      workspaceApps: controller.apps(apps), savingKeys: controller.savingKeys(), workspaces: [{ workspace_id: 'default', name: 'Default', status: 'active' }]
    }));
    beginSettingsBindings();
    const toggle = document.querySelector<HTMLInputElement>('[data-app-toggle]')!;
    bindControl(toggle, 'change', () => { saving = controller.setEnabled(apps[0], toggle.checked); void saving.catch(() => {}); });
  };
  const updated = vi.fn((item: WorkspaceApp, enabled: boolean) => { apps = [{ ...item, status: enabled ? 'enabled' : 'disabled' }]; });
  const controller = createWorkspaceAppController({ render, updated });
  render();
  return { controller, updated, render, saving: () => saving! };
}

it('rolls back a rejected app switch and re-enables the controls', async () => {
  let reject!: (error: Error) => void;
  vi.mocked(setWorkspaceAppEnabled).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  const flow = mount(); const toggle = document.querySelector<HTMLInputElement>('[data-app-toggle]')!;
  toggle.click(); flow.render();
  expect(toggle.checked).toBe(true); expect(toggle.disabled).toBe(true);
  expect(document.querySelector('[data-app-row] small')!.textContent).toContain('enabled');
  expect(document.querySelector<HTMLButtonElement>('[data-app-uninstall]')!.disabled).toBe(true);
  reject(new Error('Rejected')); await expect(flow.saving()).rejects.toThrow('Rejected');
  expect(toggle.checked).toBe(false); expect(toggle.disabled).toBe(false);
  expect(document.querySelector('[data-app-row] small')!.textContent).toContain('disabled');
  expect(flow.updated).not.toHaveBeenCalled();
});

it('retains the acknowledged enabled status after optimism is removed', async () => {
  vi.mocked(setWorkspaceAppEnabled).mockResolvedValue({});
  const flow = mount(); document.querySelector<HTMLInputElement>('[data-app-toggle]')!.click(); await flow.saving();
  expect(document.querySelector<HTMLInputElement>('[data-app-toggle]')!.checked).toBe(true);
  expect(document.querySelector<HTMLInputElement>('[data-app-toggle]')!.disabled).toBe(false);
  expect(flow.controller.savingKeys().size).toBe(0);
});

it('does not acknowledge a late enable after reset', async () => {
  let finish!: (value: object) => void;
  vi.mocked(setWorkspaceAppEnabled).mockReturnValue(new Promise(done => { finish = done; }));
  const flow = mount(); document.querySelector<HTMLInputElement>('[data-app-toggle]')!.click();
  flow.controller.reset(); clearSettingsDomCache(); flow.render(); finish({}); await flow.saving();
  expect(flow.updated).not.toHaveBeenCalled();
  expect(document.querySelector<HTMLInputElement>('[data-app-toggle]')!.checked).toBe(false);
  expect(flow.controller.savingKeys().size).toBe(0);
});
