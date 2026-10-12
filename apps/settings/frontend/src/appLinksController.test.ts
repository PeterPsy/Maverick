// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createAppLinksController } from './appLinksController';
import { getAppDependencies, loadAppRegistry, saveAppDependencySelection } from './adminApi';
import type { AppDependenciesPayload, WorkspaceApp } from './adminApi';
import { appLinksPageHtml } from './appLinksPage';
import { clearSettingsDomCache, patchSettingsDom, rememberSettingsDrafts } from './settingsDom';
import { beginSettingsBindings, bindControl } from './controlBindings';
vi.mock('./adminApi', () => ({ getAppDependencies: vi.fn(), loadAppRegistry: vi.fn(), saveAppDependencySelection: vi.fn() }));
afterEach(() => vi.resetAllMocks());
beforeEach(() => { clearSettingsDomCache(); document.body.innerHTML = '<div id="app"></div>'; rememberSettingsDrafts(document.getElementById('app')!); });

const apps = [{ app_id: 'consumer', workspace_id: 'default', status: 'enabled' }] as WorkspaceApp[];
const payload = (selected = 'a', workspace_id = 'default'): AppDependenciesPayload => ({ workspace_id, consumer_app_id: 'consumer', status: 'resolved', dependencies: [{
  alias: 'provider', interface: 'test', version: '1', required: true, cardinality: 'one', description: '', status: 'resolved',
  selected_provider_app_ids: [selected], stale_provider_app_ids: [], blocked_reason: null,
  candidates: ['a', 'b'].map(app_id => ({ app_id, name: app_id, version: '1', interface: 'test', interface_version: '1', description: '', surfaces: [] }))
}] });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function mount() {
  let saving: Promise<void>;
  let reading: Promise<void>;
  const render = () => {
    patchSettingsDom(document.getElementById('app')!, appLinksPageHtml({ ...controller.viewState(), workspaceApps: apps }));
    beginSettingsBindings();
    document.querySelectorAll<HTMLInputElement>('[data-dependency-choice]').forEach(input => bindControl(input, 'change', () => {
      saving = controller.saveDependencySelection('consumer', 'provider', [input.dataset.dependencyChoice!.split(':').pop()!]);
      void saving.catch(() => {});
    }));
    bindControl(document.getElementById('settings-refresh-app-links'), 'click', () => { reading = controller.ensureLoaded('default', apps, true); });
  };
  const publishChanged = vi.fn();
  const controller = createAppLinksController({ publishChanged, render, setNotice: vi.fn() });
  return { controller, publishChanged, saving: () => saving!, reading: () => reading! };
}

it.each(['before', 'after'])('cleans up a save when the refresh completes %s its acknowledgement', async order => {
  vi.mocked(loadAppRegistry).mockResolvedValue([]);
  vi.mocked(getAppDependencies).mockResolvedValue(payload());
  const flow = mount(); await flow.controller.ensureLoaded('default', apps);
  const save = deferred<AppDependenciesPayload>(); const read = deferred<AppDependenciesPayload>();
  vi.mocked(saveAppDependencySelection).mockReturnValueOnce(save.promise);
  vi.mocked(getAppDependencies).mockReturnValueOnce(read.promise);
  document.querySelector<HTMLInputElement>('[data-dependency-choice="consumer:provider:b"]')!.click();
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice="consumer:provider:b"]')!.checked).toBe(true);
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice]')!.disabled).toBe(true);
  document.querySelector<HTMLButtonElement>('#settings-refresh-app-links')!.click();
  if (order === 'before') { read.resolve(payload()); await flow.reading(); }
  save.resolve(payload('b')); await flow.saving();
  if (order === 'after') { read.resolve(payload()); await flow.reading(); }
  expect(flow.controller.viewState().savingKeys.size).toBe(0);
  expect(flow.controller.viewState().isLoading).toBe(false);
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice="consumer:provider:b"]')!.checked).toBe(true);
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice]')!.disabled).toBe(false);
  expect(flow.publishChanged).toHaveBeenCalledOnce();
});

it('rolls back a rejected provider choice and unlocks its real controls after refresh', async () => {
  vi.mocked(loadAppRegistry).mockResolvedValue([]);
  vi.mocked(getAppDependencies).mockResolvedValue(payload());
  const flow = mount(); await flow.controller.ensureLoaded('default', apps);
  const save = deferred<AppDependenciesPayload>();
  vi.mocked(saveAppDependencySelection).mockReturnValueOnce(save.promise);
  document.querySelector<HTMLInputElement>('[data-dependency-choice="consumer:provider:b"]')!.click();
  document.querySelector<HTMLButtonElement>('#settings-refresh-app-links')!.click(); await flow.reading();
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice="consumer:provider:b"]')!.checked).toBe(true);
  save.reject(new Error('Rejected')); await expect(flow.saving()).rejects.toThrow('Rejected');
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice="consumer:provider:a"]')!.checked).toBe(true);
  expect(document.querySelector<HTMLInputElement>('[data-dependency-choice]')!.disabled).toBe(false);
  expect(flow.controller.viewState().savingKeys.size).toBe(0);
});

it('ignores an old save after reset without unlocking a newer save of the same link', async () => {
  vi.mocked(loadAppRegistry).mockResolvedValue([]);
  vi.mocked(getAppDependencies).mockResolvedValue(payload());
  const flow = mount(); await flow.controller.ensureLoaded('default', apps);
  const old = deferred<AppDependenciesPayload>(); const current = deferred<AppDependenciesPayload>();
  vi.mocked(saveAppDependencySelection).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
  const oldSave = flow.controller.saveDependencySelection('consumer', 'provider', ['b']);
  flow.controller.reset();
  expect(flow.controller.viewState().savingKeys.size).toBe(0);
  await flow.controller.ensureLoaded('default', apps);
  const currentSave = flow.controller.saveDependencySelection('consumer', 'provider', ['b']);
  old.resolve(payload('b')); await oldSave;
  expect(flow.publishChanged).not.toHaveBeenCalled();
  expect(flow.controller.viewState().savingKeys.size).toBe(1);
  current.resolve(payload('b')); await currentSave;
  expect(flow.publishChanged).toHaveBeenCalledOnce();
  expect(flow.controller.viewState().savingKeys.size).toBe(0);
});

it('limits dependency inventory concurrency to four apps', async () => {
  vi.mocked(loadAppRegistry).mockResolvedValue([]);
  let active = 0; let maximum = 0;
  vi.mocked(getAppDependencies).mockImplementation(async appId => {
    active++; maximum = Math.max(maximum, active);
    await Promise.resolve(); active--;
    return { workspace_id: 'default', consumer_app_id: appId, status: 'resolved', dependencies: [] };
  });
  const controller = createAppLinksController({ publishChanged: vi.fn(), render: vi.fn(), setNotice: vi.fn() });
  const apps = Array.from({ length: 12 }, (_, index) => ({ app_id: `app-${index}`, workspace_id: 'default', status: 'enabled' })) as WorkspaceApp[];
  await controller.ensureLoaded('default', apps);
  expect(getAppDependencies).toHaveBeenCalledTimes(12);
  expect(maximum).toBe(4);
});

it('does not publish a registry that finished after a workspace reset', async () => {
  let finish!: (value: []) => void;
  vi.mocked(loadAppRegistry).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const controller = createAppLinksController({ publishChanged: vi.fn(), render: vi.fn(), setNotice: vi.fn() });
  const pending = controller.ensureLoaded('old', []);
  controller.reset(); finish([]); await pending;
  expect(controller.viewState().appRegistry).toEqual([]);
  expect(controller.viewState().isLoading).toBe(false);
});
