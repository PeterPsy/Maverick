import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { StorageFile } from './types';

vi.mock('./storageFileCacheClient', () => ({ openStorageFileFromDeviceCache: vi.fn() }));
vi.mock('./storageApi', () => ({
  decodeBase64: vi.fn(), previewDriveFile: vi.fn(), readPreviewTable: vi.fn(), readPreviewText: vi.fn(),
  renderPreview: vi.fn(), renderThumbnail: vi.fn(), storageMediaStreamUrl: () => '/media',
}));
import { openStorageFileFromDeviceCache } from './storageFileCacheClient';
import { readPreviewText, renderPreview } from './storageApi';
import { clearPreviewCache, loadFullPreview } from './previewCache';

const file = { id: 'file', provider: 'local', preview_kind: 'image', size_bytes: 10,
  modified_at: '2026-09-20', extension: '.png' } as StorageFile;

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});
afterEach(() => { clearPreviewCache(); vi.restoreAllMocks(); });

describe('independent preview consumers', () => {
  it('a cancelled first reader cannot poison another reader or the completed cache', async () => {
    const resolvers: Array<(blob: Blob) => void> = [];
    vi.mocked(openStorageFileFromDeviceCache).mockImplementation(() => new Promise(resolve => resolvers.push(resolve)));
    const controller = new AbortController();
    const first = loadFullPreview(file, controller.signal);
    const cancelled = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const second = loadFullPreview(file);
    controller.abort();
    resolvers[0](new Blob(['first']));
    await cancelled;
    resolvers[1](new Blob(['second']));
    const good = await second;
    const cached = await loadFullPreview(file);
    expect(good.url).toBe('blob:preview');
    expect(cached.url).toBe(good.url);
    expect(openStorageFileFromDeviceCache).toHaveBeenCalledTimes(2);
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    good.release();
    cached.release();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });

  it('cancelling a conversion never triggers its text fallback', async () => {
    let finish!: (value: Awaited<ReturnType<typeof renderPreview>>) => void;
    vi.mocked(renderPreview).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const controller = new AbortController();
    const result = loadFullPreview({ ...file, preview_kind: 'document', extension: '.docx' }, controller.signal);
    const cancelled = expect(result).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    controller.abort();
    finish({ file, content_type: 'application/pdf', preview_kind: 'pdf', renderer: 'libreoffice', stream_url: '/converted' });
    await cancelled;
    expect(readPreviewText).not.toHaveBeenCalled();
  });
});
