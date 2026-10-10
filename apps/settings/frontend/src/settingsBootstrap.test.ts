import { afterEach, expect, it, vi } from 'vitest';
import { loadSettingsBootstrap } from './settingsBootstrap';
import { getPlatformSettings, loadUsers, loadWorkspaces, loadWorkspaceApps, requestJson } from './adminApi';

vi.mock('./adminApi', () => ({ getPlatformSettings: vi.fn(), loadUsers: vi.fn(),
  loadWorkspaces: vi.fn(), loadWorkspaceApps: vi.fn(), requestJson: vi.fn() }));
afterEach(() => vi.resetAllMocks());

it('publishes Platform settings before a slow inventory finishes', async () => {
  let resolve!: (value: never[]) => void;
  vi.mocked(loadUsers).mockReturnValue(new Promise(done => { resolve = done; }));
  vi.mocked(loadWorkspaces).mockResolvedValue([]);
  vi.mocked(loadWorkspaceApps).mockResolvedValue([]);
  vi.mocked(requestJson).mockResolvedValue(null);
  const settings = { workspace: { workspace_id: 'default' } } as Awaited<ReturnType<typeof getPlatformSettings>>;
  vi.mocked(getPlatformSettings).mockResolvedValue(settings);
  const context = { isCurrent: () => true, publishPlatform: vi.fn(), publishInventory: vi.fn(), reportError: vi.fn() };
  const pending = loadSettingsBootstrap(context);
  await Promise.resolve();
  expect(context.publishPlatform).toHaveBeenCalledWith(settings);
  expect(context.publishInventory).not.toHaveBeenCalled();
  resolve([]);
  await pending;
  expect(context.publishInventory).toHaveBeenCalledOnce();
});

it('does not publish results from a superseded refresh', async () => {
  vi.mocked(loadUsers).mockResolvedValue([]);
  vi.mocked(loadWorkspaces).mockResolvedValue([]);
  vi.mocked(loadWorkspaceApps).mockResolvedValue([]);
  vi.mocked(requestJson).mockResolvedValue(null);
  vi.mocked(getPlatformSettings).mockRejectedValue(new Error('Old request'));
  const context = { isCurrent: () => false, publishPlatform: vi.fn(), publishInventory: vi.fn(), reportError: vi.fn() };
  await loadSettingsBootstrap(context);
  expect(context.publishPlatform).not.toHaveBeenCalled();
  expect(context.publishInventory).not.toHaveBeenCalled();
  expect(context.reportError).not.toHaveBeenCalled();
});
