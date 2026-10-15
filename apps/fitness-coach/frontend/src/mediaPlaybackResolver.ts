import { callStorageBackend, currentStorageAppId } from './api';
import { elapsedMediaMetricMs, mediaMetricNow, recordMediaPlaybackMetric } from './mediaPlaybackMetrics';
import type { ExerciseMediaRef, MediaPlaybackResolution } from './types';

const LOCAL_BLOB_FALLBACK_MAX_BYTES = 25 * 1024 * 1024;

type CacheEntry = {
  controller: AbortController | null;
  promise: Promise<MediaPlaybackResolution>;
  resolution?: MediaPlaybackResolution;
};

type AssetPreloadEntry = {
  element: HTMLImageElement | HTMLVideoElement | null;
  promise: Promise<MediaPlaybackResolution>;
  resolution?: MediaPlaybackResolution;
};

const mediaPlaybackCache = new Map<string, CacheEntry>();
const mediaAssetPreloadCache = new Map<string, AssetPreloadEntry>();
const storageFileInfoMetricCache = new Map<string, Promise<void>>();

export function initialMediaResolution(): MediaPlaybackResolution {
  return { status: 'idle', url: '', mediaKind: 'none', detail: '' };
}

export async function resolveMediaPlayback(media: ExerciseMediaRef | null, storageAppId = currentStorageAppId()): Promise<MediaPlaybackResolution> {
  if (!media) {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'This segment has no playable Storage media.' };
  }
  if (media.preview_kind !== 'image' && media.preview_kind !== 'video') {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'This file is not playable in Work mode V1.' };
  }
  const key = mediaCacheKey(media, storageAppId, 'stream');
  const cached = mediaPlaybackCache.get(key);
  if (cached?.resolution && cached.resolution.status !== 'ready') {
    mediaPlaybackCache.delete(key);
  } else if (cached) {
    recordMediaPlaybackMetric({
      event: 'media.resolve.cache_hit',
      media_key: key,
      provider: media.kind,
      media_kind: media.preview_kind,
      status: cached.resolution?.status || 'pending'
    });
    return cached.promise;
  }
  const startedAt = mediaMetricNow();
  const controller = typeof AbortController === 'undefined' ? null : new AbortController();
  const entry: CacheEntry = {
    controller,
    promise: resolveMediaPlaybackUncached(media, storageAppId, controller?.signal).then((resolution) => {
      if (controller?.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      entry.resolution = resolution;
      recordMediaPlaybackMetric({
        event: 'media.resolve',
        media_key: key,
        provider: media.kind,
        media_kind: media.preview_kind,
        status: resolution.status,
        duration_ms: elapsedMediaMetricMs(startedAt)
      });
      return resolution;
    }).catch((error) => {
      if (mediaPlaybackCache.get(key) === entry) mediaPlaybackCache.delete(key);
      recordMediaPlaybackMetric({
        event: 'media.resolve',
        media_key: key,
        provider: media.kind,
        media_kind: media.preview_kind,
        status: error instanceof Error && error.name === 'AbortError' ? 'aborted' : 'error',
        duration_ms: elapsedMediaMetricMs(startedAt),
        detail: error instanceof Error ? error.message : 'Storage media could not be resolved.'
      });
      if (error instanceof Error && error.name === 'AbortError') {
        return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Media resolution was canceled.' };
      }
      return { status: 'error', url: '', mediaKind: 'none', detail: error instanceof Error ? error.message : 'Storage media could not be resolved.', canRetry: true };
    })
  };
  mediaPlaybackCache.set(key, entry);
  return entry.promise;
}

export function cachedMediaPlayback(media: ExerciseMediaRef | null, storageAppId = currentStorageAppId()): MediaPlaybackResolution | null {
  if (!media) return null;
  return mediaPlaybackCache.get(mediaCacheKey(media, storageAppId, 'stream'))?.resolution || null;
}

export async function preloadMediaPlayback(media: ExerciseMediaRef | null, storageAppId = currentStorageAppId()): Promise<MediaPlaybackResolution> {
  if (!media) {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'This segment has no playable Storage media.' };
  }
  const key = mediaCacheKey(media, storageAppId, 'asset-preload');
  const streamKey = mediaCacheKey(media, storageAppId, 'stream');
  const cached = mediaAssetPreloadCache.get(key);
  if (cached) {
    recordMediaPlaybackMetric({
      event: 'media.asset_preload.cache_hit',
      media_key: streamKey,
      provider: media.kind,
      media_kind: media.preview_kind,
      status: cached.resolution?.status || 'pending'
    });
    return cached.promise;
  }

  const startedAt = mediaMetricNow();
  const entry: AssetPreloadEntry = {
    element: null,
    promise: Promise.resolve(initialMediaResolution())
  };
  entry.promise = resolveMediaPlayback(media, storageAppId).then(async (resolution) => {
    if (resolution.status === 'ready' && resolution.url) {
      await preloadResolvedMedia(resolution, entry);
    }
    entry.resolution = resolution;
    recordMediaPlaybackMetric({
      event: 'media.asset_preload',
      media_key: streamKey,
      provider: media.kind,
      media_kind: media.preview_kind,
      status: resolution.status,
      duration_ms: elapsedMediaMetricMs(startedAt)
    });
    return resolution;
  }).catch((error) => {
    mediaAssetPreloadCache.delete(key);
    recordMediaPlaybackMetric({
      event: 'media.asset_preload',
      media_key: streamKey,
      provider: media.kind,
      media_kind: media.preview_kind,
      status: 'error',
      duration_ms: elapsedMediaMetricMs(startedAt),
      detail: error instanceof Error ? error.message : 'Storage media could not be preloaded.'
    });
    return {
      status: 'error',
      url: '',
      mediaKind: 'none',
      detail: error instanceof Error ? error.message : 'Storage media could not be preloaded.',
      canRetry: true
    };
  });
  mediaAssetPreloadCache.set(key, entry);
  return entry.promise;
}

async function preloadResolvedMedia(resolution: MediaPlaybackResolution, entry: AssetPreloadEntry): Promise<void> {
  if (typeof document === 'undefined') return;

  if (resolution.mediaKind === 'image') {
    await preloadImage(resolution.url, entry);
    return;
  }

  if (resolution.mediaKind === 'video') {
    await preloadVideo(resolution.url, entry);
  }
}

function preloadImage(url: string, entry: AssetPreloadEntry): Promise<void> {
  return new Promise((resolve) => {
    const image = new Image();
    entry.element = image;
    const settle = () => resolve();
    image.onload = settle;
    image.onerror = settle;
    image.decoding = 'async';
    image.src = url;
    if (image.complete) settle();
  });
}

function preloadVideo(url: string, entry: AssetPreloadEntry): Promise<void> {
  return new Promise((resolve) => {
    const video = document.createElement('video');
    entry.element = video;
    let settled = false;
    const settle = () => {
      if (settled) return;
      settled = true;
      video.removeEventListener('loadeddata', settle);
      video.removeEventListener('canplay', settle);
      video.removeEventListener('error', settle);
      resolve();
    };
    video.muted = true;
    video.playsInline = true;
    video.setAttribute('webkit-playsinline', 'true');
    video.preload = 'auto';
    video.addEventListener('loadeddata', settle, { once: true });
    video.addEventListener('canplay', settle, { once: true });
    video.addEventListener('error', settle, { once: true });
    video.src = url;
    video.load();
    if (video.readyState >= 2) settle();
  });
}

async function resolveMediaPlaybackUncached(media: ExerciseMediaRef, storageAppId: string, signal?: AbortSignal): Promise<MediaPlaybackResolution> {
  if (media.kind === 'local_file') {
    void warmStorageFileInfoMetric(media, storageAppId, signal);
    if (!media.file_id) {
      return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Local media needs a stable Storage file_id.' };
    }
    const params = new URLSearchParams();
    params.set('file_id', media.file_id);
    const digest = String(media.sha256 || '').trim();
    const sourceVersion = digest ? `sha256:${digest}` : String(media.etag_or_version || '').startsWith('sha256:') ? media.etag_or_version : '';
    if (sourceVersion) params.set('source_version', sourceVersion);
    if (media.preview_kind === 'video') params.set('preview', 'browser');
    return {
      status: 'ready',
      url: `/api/apps/${encodeURIComponent(storageAppId)}/media?${params.toString()}`,
      mediaKind: media.preview_kind,
      detail: ''
    };
  }
  return resolveDriveLocalization(media, storageAppId, signal);
}

export async function createLocalBlobFallback(media: ExerciseMediaRef, storageAppId = currentStorageAppId()): Promise<MediaPlaybackResolution> {
  if (media.kind !== 'local_file') {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Blob URL fallback is available only for local Storage files.' };
  }
  if ((media.size_bytes || 0) > LOCAL_BLOB_FALLBACK_MAX_BYTES) {
    return {
      status: 'blocked',
      url: '',
      mediaKind: 'none',
      detail: 'This file cannot be played with the bounded fallback. Open it in Storage or use a Storage media stream.'
    };
  }
  const key = mediaCacheKey(media, storageAppId, 'blob');
  const cached = mediaPlaybackCache.get(key);
  if (cached) return cached.promise;
  const controller = typeof AbortController === 'undefined' ? null : new AbortController();
  const entry: CacheEntry = {
    controller,
    promise: createLocalBlobFallbackUncached(media, storageAppId, controller?.signal).then((resolution) => {
      entry.resolution = resolution;
      return resolution;
    }).catch((error) => {
      mediaPlaybackCache.delete(key);
      if (error instanceof Error && error.name === 'AbortError') {
        return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Media fallback was canceled.' };
      }
      return { status: 'error', url: '', mediaKind: 'none', detail: error instanceof Error ? error.message : 'Storage fallback could not be loaded.', canRetry: true };
    })
  };
  mediaPlaybackCache.set(key, entry);
  return entry.promise;
}

async function createLocalBlobFallbackUncached(media: Extract<ExerciseMediaRef, { kind: 'local_file' }>, storageAppId: string, signal?: AbortSignal): Promise<MediaPlaybackResolution> {
  const startedAt = mediaMetricNow();
  let payload: { content_base64: string; file?: { content_type?: string } };
  try {
    payload = await callStorageBackend<{ content_base64: string; file?: { content_type?: string } }>(
      { action: 'file.content.read', workspace_relative_path: media.workspace_relative_path, max_bytes: LOCAL_BLOB_FALLBACK_MAX_BYTES },
      storageAppId,
      { signal }
    );
    recordMediaPlaybackMetric({
      event: 'storage.file.content.read',
      media_key: mediaCacheKey(media, storageAppId, 'stream'),
      provider: media.kind,
      media_kind: media.preview_kind,
      status: 'ready',
      duration_ms: elapsedMediaMetricMs(startedAt)
    });
  } catch (error) {
    recordMediaPlaybackMetric({
      event: 'storage.file.content.read',
      media_key: mediaCacheKey(media, storageAppId, 'stream'),
      provider: media.kind,
      media_kind: media.preview_kind,
      status: error instanceof Error && error.name === 'AbortError' ? 'aborted' : 'error',
      duration_ms: elapsedMediaMetricMs(startedAt),
      detail: error instanceof Error ? error.message : 'Storage fallback could not be loaded.'
    });
    throw error;
  }
  const binary = Uint8Array.from(atob(payload.content_base64), (char) => char.charCodeAt(0));
  const blob = new Blob([binary], { type: payload.file?.content_type || media.content_type || 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  return { status: 'ready', url, mediaKind: media.preview_kind, detail: '', revoke: () => URL.revokeObjectURL(url) };
}

async function resolveDriveLocalization(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId: string, signal?: AbortSignal): Promise<MediaPlaybackResolution> {
  const body = driveLocalizationBody(media);
  const statusPayload = await callTimedDriveBackend<DriveLocalizationPayload>(
    { ...body, action: 'file.localize_status' },
    storageAppId,
    signal,
    media,
    'storage.file.localize_status'
  );
  const statusResolution = driveLocalizationResolution(statusPayload, media, storageAppId);
  if (statusResolution?.status === 'ready') return statusResolution;
  const action = statusResolution?.status === 'error' ? 'file.localize_retry' : 'file.localize';
  const localizePayload = await callTimedDriveBackend<DriveLocalizationPayload>(
    { ...body, action },
    storageAppId,
    signal,
    media,
    `storage.${action}`
  );
  return driveLocalizationResolution(localizePayload, media, storageAppId) || {
    status: 'error', url: '', mediaKind: media.preview_kind,
    detail: 'Storage did not finish preparing this Drive media.', canRetry: true
  };
}

type StorageFileInfoPayload = {
  file?: {
    provider?: string;
    preview_kind?: string;
  };
};

function warmStorageFileInfoMetric(media: ExerciseMediaRef, storageAppId: string, signal?: AbortSignal) {
  const key = mediaCacheKey(media, storageAppId, 'file-info');
  if (storageFileInfoMetricCache.has(key)) return storageFileInfoMetricCache.get(key);

  const startedAt = mediaMetricNow();
  const promise = callStorageBackend<StorageFileInfoPayload>(storageFileInfoBody(media), storageAppId, { signal }).then((payload) => {
    recordMediaPlaybackMetric({
      event: 'storage.file_info',
      media_key: mediaCacheKey(media, storageAppId, 'stream'),
      provider: media.kind,
      media_kind: payload.file?.preview_kind || media.preview_kind,
      status: 'ready',
      duration_ms: elapsedMediaMetricMs(startedAt)
    });
  }).catch((error) => {
    if (error instanceof Error && error.name === 'AbortError') {
      storageFileInfoMetricCache.delete(key);
    }
    recordMediaPlaybackMetric({
      event: 'storage.file_info',
      media_key: mediaCacheKey(media, storageAppId, 'stream'),
      provider: media.kind,
      media_kind: media.preview_kind,
      status: error instanceof Error && error.name === 'AbortError' ? 'aborted' : 'error',
      duration_ms: elapsedMediaMetricMs(startedAt),
      detail: error instanceof Error ? error.message : 'Storage file_info failed.'
    });
  });
  storageFileInfoMetricCache.set(key, promise);
  return promise;
}

function storageFileInfoBody(media: ExerciseMediaRef) {
  if (media.kind === 'local_file') {
    if (media.file_id) return { action: 'file_info', file_id: media.file_id };
    return { action: 'file_info', workspace_relative_path: media.workspace_relative_path };
  }
  return { action: 'file_info', file_id: media.stable_storage_file_id };
}

async function callTimedDriveBackend<T extends DriveLocalizationPayload>(
  body: Record<string, unknown>,
  storageAppId: string,
  signal: AbortSignal | undefined,
  media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>,
  event: string
): Promise<T> {
  const startedAt = mediaMetricNow();
  try {
    const payload = await callStorageBackend<T>(body, storageAppId, { signal });
    const status = driveLocalizationStatus(payload);
    recordMediaPlaybackMetric({
      event,
      media_key: mediaCacheKey(media, storageAppId, 'stream'),
      provider: media.kind,
      media_kind: media.preview_kind,
      status,
      drive_cache_status: driveLocalizationCacheStatus(payload),
      duration_ms: elapsedMediaMetricMs(startedAt)
    });
    return payload;
  } catch (error) {
    recordMediaPlaybackMetric({
      event,
      media_key: mediaCacheKey(media, storageAppId, 'stream'),
      provider: media.kind,
      media_kind: media.preview_kind,
      status: error instanceof Error && error.name === 'AbortError' ? 'aborted' : 'error',
      drive_cache_status: 'error',
      duration_ms: elapsedMediaMetricMs(startedAt),
      detail: error instanceof Error ? error.message : 'Storage Drive request failed.'
    });
    throw error;
  }
}

export function driveMediaStreamUrl(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId = currentStorageAppId()) {
  const params = new URLSearchParams();
  params.set('stable_storage_file_id', media.stable_storage_file_id);
  params.set('connection_id', media.connection_id);
  params.set('drive_file_id', media.drive_file_id);
  const sourceVersion = String(media.source_version || media.etag_or_version || '').trim();
  if (sourceVersion) params.set('source_version', sourceVersion);
  return `/api/apps/${encodeURIComponent(storageAppId)}/media?${params.toString()}`;
}

export function mediaCacheKey(media: ExerciseMediaRef, storageAppId = currentStorageAppId(), mode = 'stream') {
  const sourceVersion = media.kind === 'local_file'
    ? String(media.etag_or_version || media.sha256 || '').trim()
    : String(media.source_version || media.etag_or_version || '').trim();
  const identity = media.kind === 'local_file'
    ? media.file_id
    : `${media.stable_storage_file_id}:${media.connection_id}:${media.drive_file_id}`;
  return `${mode}:${storageAppId}:${media.kind}:${identity}:${sourceVersion}`;
}

export function cancelMediaPlayback(media: ExerciseMediaRef, storageAppId = currentStorageAppId()) {
  ['stream', 'blob', 'asset-preload'].forEach((mode) => {
    const key = mediaCacheKey(media, storageAppId, mode);
    const playbackEntry = mediaPlaybackCache.get(key);
    playbackEntry?.controller?.abort();
    playbackEntry?.resolution?.revoke?.();
    mediaPlaybackCache.delete(key);
    const preloadEntry = mediaAssetPreloadCache.get(key);
    disposeAssetPreload(preloadEntry);
    mediaAssetPreloadCache.delete(key);
  });
}

export function retainMediaPlayback(mediaList: ExerciseMediaRef[], storageAppId = currentStorageAppId()) {
  const activeStreamKeys = new Set(mediaList.map((media) => mediaCacheKey(media, storageAppId, 'stream')));
  const modes = ['blob', 'asset-preload'];
  const allowedKeys = new Set(mediaList.flatMap((media) => modes.map((mode) => mediaCacheKey(media, storageAppId, mode))));
  mediaPlaybackCache.forEach((entry, key) => {
    if (key.startsWith('stream:')) {
      if (!activeStreamKeys.has(key) && !entry.resolution) {
        entry.controller?.abort();
        mediaPlaybackCache.delete(key);
      }
      return;
    }
    if (allowedKeys.has(key)) return;
    entry.controller?.abort();
    entry.resolution?.revoke?.();
    mediaPlaybackCache.delete(key);
  });
  mediaAssetPreloadCache.forEach((entry, key) => {
    if (allowedKeys.has(key)) return;
    disposeAssetPreload(entry);
    mediaAssetPreloadCache.delete(key);
  });
}

export function clearMediaPlaybackCache() {
  mediaPlaybackCache.forEach((entry) => {
    entry.controller?.abort();
    entry.resolution?.revoke?.();
  });
  mediaPlaybackCache.clear();
  storageFileInfoMetricCache.clear();
  mediaAssetPreloadCache.forEach((entry) => disposeAssetPreload(entry));
  mediaAssetPreloadCache.clear();
}

export function latestMediaPlaybackError(media: ExerciseMediaRef, storageAppId = currentStorageAppId()) {
  const resolution = cachedMediaPlayback(media, storageAppId);
  return resolution?.status === 'error' ? resolution.detail : '';
}

type DriveLocalizationPayload = {
  status?: string;
  stream_url?: string;
  detail?: string;
  error?: string;
  localization?: {
    status?: string;
    detail?: string;
    error?: string;
    can_retry?: boolean;
    can_cancel?: boolean;
    cache_hit?: boolean;
  };
};

function driveLocalizationResolution(payload: DriveLocalizationPayload, media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId: string): MediaPlaybackResolution | null {
  const status = driveLocalizationStatus(payload);
  const detail = String(payload.localization?.detail || payload.detail || payload.localization?.error || payload.error || '');
  if (status === 'ready' || status === 'localized') {
    const url = storageMediaStreamUrl(payload.stream_url, storageAppId);
    return { status: 'ready', url, mediaKind: media.preview_kind, detail: '' };
  }
  if (status === 'error' || status === 'failed' || status === 'canceled') {
    return {
      status: 'error',
      url: driveMediaStreamUrl(media, storageAppId),
      mediaKind: media.preview_kind,
      detail: detail || 'Storage could not prepare this Drive media for playback.',
      canRetry: payload.localization?.can_retry !== false,
      canCancel: Boolean(payload.localization?.can_cancel)
    };
  }
  if (status === 'localizing' || status === 'pending' || status === 'queued') {
    return {
      status: 'localizing',
      url: driveMediaStreamUrl(media, storageAppId),
      mediaKind: media.preview_kind,
      detail: detail || 'Storage is preparing the Drive media.',
      canRetry: Boolean(payload.localization?.can_retry),
      canCancel: Boolean(payload.localization?.can_cancel)
    };
  }
  return null;
}

function storageMediaStreamUrl(value: string | undefined, storageAppId: string): string {
  const route = `/api/apps/${encodeURIComponent(storageAppId)}/media`;
  if (!value || !value.startsWith(`${route}?`)) {
    throw new Error('Storage did not return a valid media stream URL.');
  }
  const parsed = new URL(value, 'https://storage.invalid');
  if (parsed.pathname !== route || parsed.origin !== 'https://storage.invalid') {
    throw new Error('Storage did not return a valid media stream URL.');
  }
  return value;
}

function driveLocalizationStatus(payload: DriveLocalizationPayload): string {
  return String(payload.localization?.status || payload.status || 'unknown');
}

function driveLocalizationCacheStatus(payload: DriveLocalizationPayload): string {
  const status = driveLocalizationStatus(payload);
  if (typeof payload.localization?.cache_hit === 'boolean') {
    return payload.localization.cache_hit ? 'hit' : status === 'ready' || status === 'localized' ? 'miss' : status;
  }
  return status;
}

function driveLocalizationBody(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>) {
  return {
    stable_storage_file_id: media.stable_storage_file_id,
    connection_id: media.connection_id,
    drive_file_id: media.drive_file_id,
    // Storage resolves the saved reference to the currently enabled account.
    // Fitness Coach does not select credentials from a saved connection id.
    _app_secret_request: { logical_names: [], required: false }
  };
}

function disposeAssetPreload(entry: AssetPreloadEntry | undefined) {
  const element = entry?.element;
  if (!element) return;
  if (element.tagName === 'VIDEO') {
    const video = element as HTMLVideoElement;
    video.pause();
    video.removeAttribute('src');
    video.load();
    return;
  }
  element.removeAttribute('src');
}
