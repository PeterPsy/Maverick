import { describe, expect, it, vi } from 'vitest';
import { callBackend, currentStorageAppId, moveItemsReferences, storageBackendEndpoint } from './storageApi';

describe('storage api client', () => {
  it('derives the mounted app backend from app and widget routes', () => {
    expect(currentStorageAppId('/apps/storage-fork/')).toBe('storage-fork');
    expect(currentStorageAppId('/api/apps/widgets/storage-fork/storage-sidebar-footer/frontend/')).toBe('storage-fork');
    expect(currentStorageAppId('/app/storage/files')).toBe('storage');
    expect(storageBackendEndpoint('storage-fork')).toBe('/api/apps/storage-fork/backend');
  });

  it('calls the selected app backend endpoint', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await expect(callBackend<{ ok: boolean }>({ action: 'catalog' }, { appId: 'storage-fork', fetchImpl })).resolves.toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage-fork/backend',
      expect.objectContaining({
        body: JSON.stringify({ action: 'catalog' }),
        method: 'POST'
      })
    );
  });

  it('sends selected file and folder moves as one backend action', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ files: [], folders: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchImpl);

    try {
      await moveItemsReferences(
        [{ role: 'generated', relative_path: 'loose.md', workspace_relative_path: 'storage/generated/loose.md' }],
        [{ role: 'generated', relative_path: 'Reports', workspace_relative_path: 'storage/generated/Reports' }],
        'generated',
        'Archive'
      );
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'move_items',
          role: 'generated',
          target_folder_relative_path: 'Archive',
          files: [{ role: 'generated', relative_path: 'loose.md', workspace_relative_path: 'storage/generated/loose.md' }],
          folders: [{ role: 'generated', relative_path: 'Reports', workspace_relative_path: 'storage/generated/Reports' }]
        }),
        method: 'POST'
      })
    );
  });
});
