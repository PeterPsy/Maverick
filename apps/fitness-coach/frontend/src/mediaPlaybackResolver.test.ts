import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearMediaPlaybackCache, createLocalBlobFallback, resolveMediaPlayback } from './mediaPlaybackResolver';
import type { ExerciseMediaRef } from './types';

function jsonResponse(payload: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => payload
  } as Response;
}

const driveMedia: Extract<ExerciseMediaRef, { kind: 'drive_file' }> = {
  kind: 'drive_file',
  provider: 'google_drive',
  stable_storage_file_id: 'file_drive',
  connection_id: 'drive_conn',
  drive_file_id: 'drive_file',
  display_path: '/My Drive/workout/video.mp4',
  name: 'video.mp4',
  content_type: 'video/mp4',
  preview_kind: 'video',
  source_version: 'v1'
};

const localMedia: Extract<ExerciseMediaRef, { kind: 'local_file' }> = {
  kind: 'local_file',
  provider: 'local',
  file_id: 'file_local',
  workspace_relative_path: 'storage/uploaded/workout/video.mp4',
  display_path: 'storage/uploaded/workout/video.mp4',
  name: 'video.mp4',
  content_type: 'video/mp4',
  preview_kind: 'video',
  size_bytes: 120
};

describe('media playback resolver', () => {
  afterEach(() => {
    clearMediaPlaybackCache();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('returns the Drive media route immediately and dedupes localization warmup', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      if (body.action === 'file.localize_status') return jsonResponse({ status: 'missing' });
      return jsonResponse({ status: 'localizing' });
    });
    vi.stubGlobal('fetch', fetchMock);

    const [first, second] = await Promise.all([
      resolveMediaPlayback(driveMedia, 'storage'),
      resolveMediaPlayback(driveMedia, 'storage')
    ]);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(first).toMatchObject({ status: 'ready', mediaKind: 'video' });
    expect(second.url).toBe(first.url);
    expect(first.url).toContain('/api/apps/storage/media?');
    expect(first.url).toContain('stable_storage_file_id=file_drive');
    expect(fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)).action)).toEqual([
      'file.localize_status',
      'file.localize'
    ]);
  });

  it('dedupes local Blob fallback and revokes Blob URLs on cache cleanup', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ content_base64: btoa('x'), file: { content_type: 'video/mp4' } }));
    const createObjectURL = vi.fn(() => 'blob:fitness-coach');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });

    const first = await createLocalBlobFallback(localMedia, 'storage');
    const second = await createLocalBlobFallback(localMedia, 'storage');
    clearMediaPlaybackCache();

    expect(first.url).toBe('blob:fitness-coach');
    expect(second.url).toBe(first.url);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fitness-coach');
  });
});
