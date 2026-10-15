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

function storageRequestActions(fetchMock: { mock: { calls: unknown[][] } }) {
  return fetchMock.mock.calls.map((call) => JSON.parse(String((call[1] as RequestInit | undefined)?.body)).action);
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

  it('localizes an unprepared Drive file even when status includes a stream URL', async () => {
    const streamUrl = '/api/apps/storage/media?stable_storage_file_id=file_current&localization_id=localized&source_version=v2';
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      if (body.action === 'file.localize_status') return jsonResponse({ status: 'not_started', stream_url: streamUrl });
      return jsonResponse({ status: 'ready', stream_url: streamUrl });
    });
    vi.stubGlobal('fetch', fetchMock);

    const [first, second] = await Promise.all([
      resolveMediaPlayback(driveMedia, 'storage'),
      resolveMediaPlayback(driveMedia, 'storage')
    ]);
    expect(first).toMatchObject({ status: 'ready', mediaKind: 'video' });
    expect(second.url).toBe(first.url);
    expect(first.url).toBe(streamUrl);
    expect(storageRequestActions(fetchMock)).toEqual([
      'file.localize_status',
      'file.localize'
    ]);
  });

  it('preserves Drive localization errors even when Storage returns a stream URL', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      stream_url: '/api/apps/storage/media?stable_storage_file_id=file_drive',
      localization: {
        status: 'error',
        detail: 'Google Drive grant is missing.',
        can_retry: true
      }
    }));
    vi.stubGlobal('fetch', fetchMock);

    const resolution = await resolveMediaPlayback(driveMedia, 'storage');
    expect(resolution).toMatchObject({
      status: 'error',
      detail: 'Google Drive grant is missing.',
      canRetry: true
    });
    expect(latestMediaPlaybackError(driveMedia, 'storage')).toBe('Google Drive grant is missing.');
    expect(storageRequestActions(fetchMock)).toEqual([
      'file.localize_status',
      'file.localize_retry'
    ]);
  });

  it('keeps resolved stream routes cached after inactive media is no longer preloaded', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      status: 'ready',
      stream_url: '/api/apps/storage/media?stable_storage_file_id=file_drive'
    }));
    vi.stubGlobal('fetch', fetchMock);

    const first = await resolveMediaPlayback(driveMedia, 'storage');
    retainMediaPlayback([], 'storage');
    const second = await resolveMediaPlayback(driveMedia, 'storage');

    expect(second.url).toBe(first.url);
    expect(storageRequestActions(fetchMock)).toEqual([
      'file.localize_status'
    ]);
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
    expect(storageRequestActions(fetchMock)).toEqual([
      'file.localize_status'
    ]);
  });

  it('restarts aborted Drive resolution when the media becomes active again', async () => {
    const requests: Array<{ action: string; signal?: AbortSignal }> = [];
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      const signal = init?.signal as AbortSignal | undefined;
      requests.push({ action: String(body.action), signal });
      return new Promise<Response>((_resolve, reject) => {
        if (signal?.aborted) {
          reject(abortError());
          return;
        }
        signal?.addEventListener('abort', () => reject(abortError()), { once: true });
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const first = resolveMediaPlayback(driveMedia, 'storage');
    retainMediaPlayback([], 'storage');
    await first;
    const second = resolveMediaPlayback(driveMedia, 'storage');

    const warmups = requests.filter((request) => request.action === 'file.localize_status');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(warmups).toHaveLength(2);
    expect(warmups[0]?.signal?.aborted).toBe(true);
    expect(warmups[1]?.signal?.aborted).toBe(false);
    clearMediaPlaybackCache();
    await second;
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

    const pending = [resolveMediaPlayback(mediaA, 'storage'), resolveMediaPlayback(mediaB, 'storage'), resolveMediaPlayback(mediaC, 'storage')];
    retainMediaPlayback([mediaB, mediaC], 'storage');

    expect(requests.find((request) => request.driveFileId === 'drive_a')?.signal?.aborted).toBe(true);
    expect(requests.find((request) => request.driveFileId === 'drive_b')?.signal?.aborted).toBe(false);
    expect(requests.find((request) => request.driveFileId === 'drive_c')?.signal?.aborted).toBe(false);
    clearMediaPlaybackCache();
    await Promise.all(pending);
  });

  it('uses the Storage-owned URL after an account or source version changes', async () => {
    const streamUrl = '/api/apps/storage/media?stable_storage_file_id=file_new_account&localization_id=current&source_version=v2';
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'ready', stream_url: streamUrl })));

    const resolved = await resolveMediaPlayback(driveMedia, 'storage');

    expect(resolved.url).toBe(streamUrl);
    expect(driveMedia.stable_storage_file_id).toBe('file_drive');
    expect(driveMedia.source_version).toBe('v1');
  });

  it('waits for localization before exposing a playable URL and leaves account selection to Storage', async () => {
    let finish!: (value: Response) => void;
    const streamUrl = '/api/apps/storage/media?stable_storage_file_id=file_current&source_version=v2';
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      if (body.action === 'file.localize_status') return jsonResponse({ status: 'not_started', stream_url: streamUrl });
      return new Promise<Response>((resolve) => { finish = resolve; });
    });
    vi.stubGlobal('fetch', fetchMock);
    const settled = vi.fn();
    const pending = resolveMediaPlayback(driveMedia, 'storage').then(settled);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(settled).not.toHaveBeenCalled();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.stable_storage_file_id).toBe('file_drive');
    expect(body._app_secret_request).toEqual({ logical_names: [], required: false });

    finish(jsonResponse({ status: 'ready', stream_url: streamUrl }));
    await pending;
    expect(settled).toHaveBeenCalledWith(expect.objectContaining({ status: 'ready', url: streamUrl }));
  });

  it('rejects stream URLs outside the selected Storage media route', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'ready', stream_url: 'https://example.com/video.mp4' })));

    expect(await resolveMediaPlayback(driveMedia, 'storage')).toMatchObject({ status: 'error', canRetry: true });
  });

  it('allows another attempt after a failed localization instead of caching the failure', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ status: 'error', detail: 'Temporary Drive failure.' }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await resolveMediaPlayback(driveMedia, 'storage')).toMatchObject({ status: 'error' });

    const streamUrl = '/api/apps/storage/media?stable_storage_file_id=file_drive&source_version=v1';
    fetchMock.mockImplementation(async () => jsonResponse({ status: 'ready', stream_url: streamUrl }));

    expect(await resolveMediaPlayback(driveMedia, 'storage')).toMatchObject({ status: 'ready', url: streamUrl });
    expect(storageRequestActions(fetchMock)).toEqual(['file.localize_status', 'file.localize_retry', 'file.localize_status']);
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

  it('requests browser playback for local videos using the Storage digest version', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({})));
    const digest = 'a'.repeat(64);
    const resolution = await resolveMediaPlayback({ ...localMedia, sha256: digest }, 'storage');
    const params = new URL(resolution.url, 'https://storage.invalid').searchParams;
    expect(params.get('file_id')).toBe('file_local');
    expect(params.get('preview')).toBe('browser');
    expect(params.get('source_version')).toBe(`sha256:${digest}`);
  });
});
