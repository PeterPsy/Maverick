import { describe, expect, it } from 'vitest';
import { storageViewFilterChangedMessage, storageViewFilterFromMessage } from './storageViewFilterEvents';
import type { StorageViewFilter } from '../types';

const viewFilter: StorageViewFilter = {
  file_ids: [],
  kind: 'pdf',
  mode: 'search',
  query: '',
  role: 'generated',
  title: '',
  updated_at: '2026-05-14T08:00:00.000000+00:00',
  workspace_relative_paths: [],
};

describe('storage view filter events', () => {
  it('builds a same-app data-changed message carrying the updated filter', () => {
    expect(storageViewFilterChangedMessage('storage', viewFilter)).toEqual({
      detail: {
        view_filter: viewFilter,
      },
      owner_app_id: 'storage',
      resource: 'view-state',
      type: 'maverick.app.data-changed',
    });
  });

  it('extracts the view filter only for the matching Storage app view-state event', () => {
    const message = storageViewFilterChangedMessage('storage', viewFilter);

    expect(storageViewFilterFromMessage(message, 'storage')).toBe(viewFilter);
    expect(storageViewFilterFromMessage({ ...message, type: 'maverick.widget.data-changed' }, 'storage')).toBe(viewFilter);
    expect(storageViewFilterFromMessage(message, 'storage-fork')).toBeNull();
    expect(storageViewFilterFromMessage({ ...message, resource: 'files' }, 'storage')).toBeNull();
  });
});
