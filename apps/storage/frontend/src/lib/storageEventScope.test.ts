import { describe, expect, it } from 'vitest';
import { storageEventAffectsView, storageScopeKey } from './storageEventScope';

const view = { role: 'generated', folder: 'reading', query: '', custom: false, drive: false };
const detail = (role: string, path: string) => [null, ...path.split('/').map((_, index, parts) => parts.slice(0, index).join('/'))]
  .map(parent => storageScopeKey(role, parent));

describe('Storage event scope', () => {
  it('preserves loaded pages when another local folder changes', () => {
    expect(storageEventAffectsView(detail('generated', 'uploads/new.md'), view)).toBe(false);
    expect(storageEventAffectsView(detail('uploaded', 'reading/new.md'), view)).toBe(false);
    expect(storageEventAffectsView(detail('generated', 'reading-not-this/new.md'), view)).toBe(false);
  });
  it('refreshes descendants, searches and unknown operations', () => {
    for (const path of ['reading/file.md', 'reading/sub/file.md']) {
      expect(storageEventAffectsView(detail('generated', path), view)).toBe(true);
    }
    expect(storageEventAffectsView(detail('generated', 'uploads/new.md'), { ...view, query: 'new' })).toBe(true);
    for (const value of [undefined, {}, [], ['invalid'], Array(129).fill('a'.repeat(64))]) {
      expect(storageEventAffectsView(value, view)).toBe(true);
    }
  });
  it('uses the backend UTF-8 SHA-256 scope encoding', () => {
    expect(storageScopeKey('generated', null)).toBe('e228942194760b52874ad8f644716abd22e4818411398f9e99956f9a685e1604');
    expect(storageScopeKey('generated', 'études')).toBe('1f8aea753c0fa8c09e4827f90abf01fb4526269dfb8f0e16c279628d0ecf2a89');
  });
});
