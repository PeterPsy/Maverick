import { afterEach, expect, it, vi } from 'vitest';
import { createAppLinksController } from './appLinksController';
import { getAppDependencies, loadAppRegistry } from './adminApi';
import type { WorkspaceApp } from './adminApi';
vi.mock('./adminApi', () => ({ getAppDependencies: vi.fn(), loadAppRegistry: vi.fn(), saveAppDependencySelection: vi.fn() }));
afterEach(() => vi.resetAllMocks());

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
