import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearMediaPlaybackCache, createLocalBlobFallback, latestMediaPlaybackError, preloadMediaPlayback, resolveMediaPlayback, retainMediaPlayback } from './mediaPlaybackResolver';
import type { ExerciseMediaRef } from './types';

function jsonResponse(payload: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => payload
  } as Response;
}

function abortError() {
  return Object.assign(new Error('Aborted'), { name: 'AbortError' });
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
    await first.warmup;

    expect(first).toMatchObject({ status: 'ready', mediaKind: 'video' });
    expect(second.url).toBe(first.url);
    expect(first.url).toContain('/api/apps/storage/media?');
    expect(first.url).toContain('stable_storage_file_id=file_drive');
    expect(fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)).action)).toEqual([
      'file.localize_status',
      'file.localize'
    ]);
  });

  it('preserves Drive localization errors for playback fallback UI', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      localization: {
        status: 'error',
        detail: 'Google Drive grant is missing.',
        can_retry: true
      }
    }));
    vi.stubGlobal('fetch', fetchMock);

    const resolution = await resolveMediaPlayback(driveMedia, 'storage');
    const warmed = await resolution.warmup;

    expect(resolution).toMatchObject({ status: 'ready', mediaKind: 'video' });
    expect(warmed).toMatchObject({
      status: 'error',
      detail: 'Google Drive grant is missing.',
      canRetry: true
    });
    expect(latestMediaPlaybackError(driveMedia, 'storage')).toBe('Google Drive grant is missing.');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('keeps resolved stream routes cached after inactive media is no longer preloaded', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      status: 'ready',
      stream_url: '/api/apps/storage/media?stable_storage_file_id=file_drive'
    }));
    vi.stubGlobal('fetch', fetchMock);

    const first = await resolveMediaPlayback(driveMedia, 'storage');
    await first.warmup;
    retainMediaPlayback([], 'storage');
    const second = await resolveMediaPlayback(driveMedia, 'storage');

    expect(second.url).toBe(first.url);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('dedupes browser preload requests for the next workout media', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      status: 'ready',
      stream_url: '/api/apps/storage/media?stable_storage_file_id=file_drive'
    }));
    vi.stubGlobal('fetch', fetchMock);

    const [first, second] = await Promise.all([
      preloadMediaPlayback(driveMedia, 'storage'),
      preloadMediaPlayback(driveMedia, 'storage')
    ]);

    expect(first).toMatchObject({ status: 'ready', mediaKind: 'video' });
    expect(second.url).toBe(first.url);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('restarts aborted Drive warmups when a cached stream route becomes active again', async () => {
    const requests: AbortSignal[] = [];
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const signal = init?.signal as AbortSignal | undefined;
      if (signal) requests.push(signal);
      return new Promise<Response>((_resolve, reject) => {
        if (signal?.aborted) {
          reject(abortError());
          return;
        }
        signal?.addEventListener('abort', () => reject(abortError()), { once: true });
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    await resolveMediaPlayback(driveMedia, 'storage');
    retainMediaPlayback([], 'storage');
    await resolveMediaPlayback(driveMedia, 'storage');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requests[0]?.aborted).toBe(true);
    expect(requests[1]?.aborted).toBe(false);
  });

  it('aborts Drive warmups outside the retained current and next media', async () => {
    const mediaA = { ...driveMedia, stable_storage_file_id: 'file_a', drive_file_id: 'drive_a', source_version: 'vA' };
    const mediaB = { ...driveMedia, stable_storage_file_id: 'file_b', drive_file_id: 'drive_b', source_version: 'vB' };
    const mediaC = { ...driveMedia, stable_storage_file_id: 'file_c', drive_file_id: 'drive_c', source_version: 'vC' };
    const requests: Array<{ driveFileId: string; signal?: AbortSignal }> = [];
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      const signal = init?.signal as AbortSignal | undefined;
      requests.push({ driveFileId: String(body.drive_file_id), signal });
      return new Promise<Response>((_resolve, reject) => {
        if (signal?.aborted) {
          reject(abortError());
          return;
        }
        signal?.addEventListener('abort', () => reject(abortError()), { once: true });
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    await resolveMediaPlayback(mediaA, 'storage');
    await resolveMediaPlayback(mediaB, 'storage');
    await resolveMediaPlayback(mediaC, 'storage');
    retainMediaPlayback([mediaB, mediaC], 'storage');

    expect(requests.find((request) => request.driveFileId === 'drive_a')?.signal?.aborted).toBe(true);
    expect(requests.find((request) => request.driveFileId === 'drive_b')?.signal?.aborted).toBe(false);
    expect(requests.find((request) => request.driveFileId === 'drive_c')?.signal?.aborted).toBe(false);
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
