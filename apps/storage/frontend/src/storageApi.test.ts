import { describe, expect, it, vi } from 'vitest';
import { callBackend, currentStorageAppId, storageBackendEndpoint } from './storageApi';

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
});
