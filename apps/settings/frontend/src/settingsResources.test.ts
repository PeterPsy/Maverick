import { afterEach, expect, it, vi } from 'vitest';
import { createSettingsResources, resourcesForPage } from './settingsResources';
import { requestJson } from './adminApi';
vi.mock('./adminApi', () => ({ requestJson: vi.fn() }));
afterEach(() => vi.resetAllMocks());

it('loads users without catalogs, persistence or session inventory', async () => {
  vi.mocked(requestJson).mockResolvedValue({ items: [] });
  const publish = vi.fn();
  const resources = createSettingsResources({ publish, changed: vi.fn() });
  await Promise.all(resourcesForPage('users').map(resource => resources.ensure(resource)));
  expect(vi.mocked(requestJson).mock.calls.map(([path]) => path)).toEqual(['/api/admin/users', '/api/admin/workspaces']);
  expect(publish).toHaveBeenCalledTimes(2);
});

it('deduplicates a pending request and publishes independent resources immediately', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(requestJson).mockImplementation(path => path.includes('/users') ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({ items: [] }));
  const publish = vi.fn();
  const resources = createSettingsResources({ publish, changed: vi.fn() });
  const users = resources.ensure('users');
  expect(resources.ensure('users')).toBe(users);
  await resources.ensure('workspaces');
  expect(resources.state('workspaces').loaded).toBe(true);
  expect(resources.state('users').loading).toBe(true);
  finish({ items: [] }); await users;
  expect(requestJson).toHaveBeenCalledTimes(2);
});

it('discards a cancelled response even when the transport does not honor abort', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(requestJson).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const publish = vi.fn();
  const resources = createSettingsResources({ publish, changed: vi.fn() });
  const pending = resources.ensure('models');
  const signal = vi.mocked(requestJson).mock.calls[0][1]?.signal;
  resources.cancelExcept(resourcesForPage('users'));
  expect(signal?.aborted).toBe(true);
  finish({ old: true }); await pending;
  expect(publish).not.toHaveBeenCalled();
  expect(resources.state('models').loaded).toBe(false);
});

it('retains loaded data on a failed refresh and retries only that resource', async () => {
  vi.mocked(requestJson).mockResolvedValueOnce({ items: [1] }).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce({ items: [2] });
  const publish = vi.fn();
  const resources = createSettingsResources({ publish, changed: vi.fn() });
  await resources.ensure('users'); await resources.ensure('users', true);
  expect(resources.state('users')).toEqual({ loaded: true, loading: false, error: 'Offline' });
  expect(publish).toHaveBeenCalledOnce();
  await resources.ensure('users', true);
  expect(resources.state('users').error).toBe('');
  expect(publish).toHaveBeenLastCalledWith('users', { items: [2] });
});
