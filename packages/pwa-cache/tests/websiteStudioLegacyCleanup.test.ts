import { afterEach, expect, it, vi } from 'vitest';
import { purgeLegacyWorkspaceSnapshots } from '../../../apps/website-studio/frontend/src/legacySnapshotCleanup';

afterEach(() => vi.unstubAllGlobals());
it('deletes every unscoped snapshot without reading values or touching other storage', () => {
  const data = new Map([
    ['website-studio:snapshot:active::/', 'private old account'],
    ['website-studio:snapshot:site::/page', 'private other workspace'],
    ['unrelated', 'keep']
  ]);
  const getItem = vi.fn(() => { throw new Error('Legacy values must never be read'); });
  vi.stubGlobal('sessionStorage', {
    get length() { return data.size; },
    key: (index: number) => [...data.keys()][index] ?? null,
    removeItem: (key: string) => data.delete(key), getItem
  });
  purgeLegacyWorkspaceSnapshots();
  purgeLegacyWorkspaceSnapshots();
  expect([...data]).toEqual([['unrelated', 'keep']]);
  expect(getItem).not.toHaveBeenCalled();
});
it('does not prevent normal server reads when browser storage is unavailable', () => {
  vi.stubGlobal('sessionStorage', { get length() { throw new Error('SecurityError'); } });
  expect(purgeLegacyWorkspaceSnapshots).not.toThrow();
});
