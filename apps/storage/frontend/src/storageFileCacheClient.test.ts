import { describe, expect, it, vi } from 'vitest';
import { openStorageFileFromDeviceCache, stableStorageFileSourceVersion } from './storageFileCacheClient';
import type { StorageFile } from './types';

function file(overrides: Partial<StorageFile> = {}): StorageFile {
  return {
    id: 'file-one',
    file_id: 'file-one',
    path_id: 'uploaded:one.txt',
    provider: 'local',
    role: 'uploaded',
    name: 'one.txt',
    relative_path: 'one.txt',
    workspace_relative_path: 'storage/uploaded/one.txt',
    extension: '.txt',
    size_bytes: 3,
    modified_at: '2026-08-31T00:00:00Z',
    content_type: 'text/plain',
    preview_kind: 'text',
    sha256: 'a'.repeat(64),
    ...overrides,
  };
}

describe('Storage parent file-cache client', () => {
  it('uses only stable local digests or provider revisions as source versions', () => {
    expect(stableStorageFileSourceVersion(file())).toBe(`sha256:${'a'.repeat(64)}`);
    expect(stableStorageFileSourceVersion(file({ provider: 'google_drive', source_version: 'drive-8', sha256: '' }))).toBe('drive-8');
    expect(stableStorageFileSourceVersion(file({ provider: 'google_drive', source_version: '', etag_or_version: 'drive-9', sha256: '' }))).toBe('drive-9');
    expect(stableStorageFileSourceVersion(file({ sha256: '', source_version: '', etag_or_version: '', modified_at: 'fallback-is-not-stable' }))).toBe('');
  });

  it('forwards only stable identity to the parent-owned broker', async () => {
    const request = vi.fn(async () => ({ blob: new Blob(['one']), source: 'cache' as const }));
    const signal = new AbortController().signal;

    const result = await openStorageFileFromDeviceCache(file(), { request, signal });

    expect(request).toHaveBeenCalledWith({
      fileId: 'file-one',
      sourceVersion: `sha256:${'a'.repeat(64)}`,
    }, { signal });
    expect(await result?.text()).toBe('one');
  });

  it('does not contact the broker when stable identity is unavailable', async () => {
    const request = vi.fn();
    await expect(openStorageFileFromDeviceCache(file({ sha256: '' }), { request })).resolves.toBeNull();
    expect(request).not.toHaveBeenCalled();
  });

  it('does not start a cache-through read above the caller preview ceiling', async () => {
    const request = vi.fn();

    await expect(openStorageFileFromDeviceCache(file({ size_bytes: 9 }), {
      maxBytes: 8,
      request,
    })).resolves.toBeNull();

    expect(request).not.toHaveBeenCalled();
  });
});
