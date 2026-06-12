import { callStorageBackend, currentStorageAppId } from './api';
import type { ExerciseMediaRef, MediaPlaybackResolution } from './types';

const LOCAL_BLOB_FALLBACK_MAX_BYTES = 25 * 1024 * 1024;

type CacheEntry = {
  controller: AbortController | null;
  promise: Promise<MediaPlaybackResolution>;
  resolution?: MediaPlaybackResolution;
};

type WarmupEntry = {
  controller: AbortController | null;
  promise: Promise<MediaPlaybackResolution | null>;
};

type AssetPreloadEntry = {
  element: HTMLImageElement | HTMLVideoElement | null;
  promise: Promise<MediaPlaybackResolution>;
  resolution?: MediaPlaybackResolution;
};

const mediaPlaybackCache = new Map<string, CacheEntry>();
const driveWarmupCache = new Map<string, WarmupEntry>();
const driveWarmupErrors = new Map<string, string>();
const driveWarmupReady = new Set<string>();
const mediaAssetPreloadCache = new Map<string, AssetPreloadEntry>();

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
  if (cached) {
    refreshCachedDriveWarmup(media, storageAppId, cached);
    return cached.promise;
  }
  const controller = typeof AbortController === 'undefined' ? null : new AbortController();
  const entry: CacheEntry = {
    controller,
    promise: resolveMediaPlaybackUncached(media, storageAppId, controller?.signal).then((resolution) => {
      entry.resolution = resolution;
      return resolution;
    }).catch((error) => {
      mediaPlaybackCache.delete(key);
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

function refreshCachedDriveWarmup(media: ExerciseMediaRef, storageAppId: string, cached: CacheEntry) {
  if (media.kind !== 'drive_file' || cached.resolution?.status !== 'ready') return;
  const warmupKey = mediaCacheKey(media, storageAppId, 'drive-warmup');
  if (driveWarmupReady.has(warmupKey)) return;
  const warmup = warmDriveLocalization(media, storageAppId);
  cached.resolution = { ...cached.resolution, warmup };
  cached.promise = Promise.resolve(cached.resolution);
}

export async function preloadMediaPlayback(media: ExerciseMediaRef | null, storageAppId = currentStorageAppId()): Promise<MediaPlaybackResolution> {
  if (!media) {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'This segment has no playable Storage media.' };
  }
  const key = mediaCacheKey(media, storageAppId, 'asset-preload');
  const cached = mediaAssetPreloadCache.get(key);
  if (cached) return cached.promise;

  const entry: AssetPreloadEntry = {
    element: null,
    promise: Promise.resolve(initialMediaResolution())
  };
  entry.promise = resolveMediaPlayback(media, storageAppId).then(async (resolution) => {
    if (resolution.status === 'ready' && resolution.url) {
      await preloadResolvedMedia(resolution, entry);
    }
    entry.resolution = resolution;
    return resolution;
  }).catch((error) => {
    mediaAssetPreloadCache.delete(key);
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
    if (!media.file_id) {
      return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Local media needs a stable Storage file_id.' };
    }
    const params = new URLSearchParams();
    params.set('file_id', media.file_id);
    const sourceVersion = String(media.etag_or_version || media.sha256 || '').trim();
    if (sourceVersion) params.set('source_version', sourceVersion);
    return {
      status: 'ready',
      url: `/api/apps/${encodeURIComponent(storageAppId)}/media?${params.toString()}`,
      mediaKind: media.preview_kind,
      detail: ''
    };
  }
  const warmup = warmDriveLocalization(media, storageAppId, signal);
  return {
    status: 'ready',
    url: driveMediaStreamUrl(media, storageAppId),
    mediaKind: media.preview_kind,
    detail: 'Storage media route is ready while Drive localization warms in the background.',
    canRetry: true,
    canCancel: true,
    warmup
  };
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
  const payload = await callStorageBackend<{ content_base64: string; file?: { content_type?: string } }>(
    { action: 'file.content.read', workspace_relative_path: media.workspace_relative_path, max_bytes: LOCAL_BLOB_FALLBACK_MAX_BYTES },
    storageAppId,
    { signal }
  );
  const binary = Uint8Array.from(atob(payload.content_base64), (char) => char.charCodeAt(0));
  const blob = new Blob([binary], { type: payload.file?.content_type || media.content_type || 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  return { status: 'ready', url, mediaKind: media.preview_kind, detail: '', revoke: () => URL.revokeObjectURL(url) };
}

function warmDriveLocalization(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId: string, linkedSignal?: AbortSignal): Promise<MediaPlaybackResolution | null> {
  const key = mediaCacheKey(media, storageAppId, 'drive-warmup');
  const cached = driveWarmupCache.get(key);
  if (cached) return cached.promise;
  driveWarmupErrors.delete(key);
  const controller = typeof AbortController === 'undefined' ? null : new AbortController();
  if (linkedSignal && controller) {
    if (linkedSignal.aborted) controller.abort();
    else linkedSignal.addEventListener('abort', () => controller.abort(), { once: true });
  }
  const promise: Promise<MediaPlaybackResolution | null> = warmDriveLocalizationUncached(media, storageAppId, controller?.signal).then((resolution) => {
    if (resolution?.status === 'ready') {
      driveWarmupReady.add(key);
    }
    if (resolution?.status === 'error') {
      driveWarmupErrors.set(key, resolution.detail);
    }
    return resolution;
  }).catch((error): MediaPlaybackResolution | null => {
    if (error instanceof Error && error.name === 'AbortError') return null;
    const detail = error instanceof Error ? error.message : 'Storage could not warm Drive media.';
    driveWarmupErrors.set(key, detail);
    return {
      status: 'error',
      url: driveMediaStreamUrl(media, storageAppId),
      mediaKind: media.preview_kind,
      detail,
      canRetry: true
    };
  });
  driveWarmupCache.set(key, { controller, promise });
  return promise;
}

async function warmDriveLocalizationUncached(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId: string, signal?: AbortSignal): Promise<MediaPlaybackResolution | null> {
  const body = driveLocalizationBody(media);
  const statusPayload = await callStorageBackend<DriveLocalizationPayload>(
    { ...body, action: 'file.localize_status' },
    storageAppId,
    { signal }
  );
  const statusResolution = driveLocalizationResolution(statusPayload, media, storageAppId);
  if (statusResolution?.status === 'ready' || statusResolution?.status === 'error') return statusResolution;
  const status = String(statusPayload.localization?.status || statusPayload.status || '');
  if (status === 'ready' || status === 'localized') return statusResolution;
  const localizePayload = await callStorageBackend<DriveLocalizationPayload>({ ...body, action: 'file.localize' }, storageAppId, { signal });
  return driveLocalizationResolution(localizePayload, media, storageAppId);
}

export function driveMediaStreamUrl(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId = currentStorageAppId()) {
  const params = new URLSearchParams();
  params.set('stable_storage_file_id', media.stable_storage_file_id);
  params.set('connection_id', media.connection_id);
  params.set('drive_file_id', media.drive_file_id);
  const sourceVersion = String(media.source_version || media.etag_or_version || '').trim();
  if (sourceVersion) params.set('source_version', sourceVersion);
  params.set('_app_secret_request', JSON.stringify(driveSecretRequest(media.connection_id)));
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
  ['stream', 'blob', 'drive-warmup', 'asset-preload'].forEach((mode) => {
    const key = mediaCacheKey(media, storageAppId, mode);
    const playbackEntry = mediaPlaybackCache.get(key);
    playbackEntry?.controller?.abort();
    playbackEntry?.resolution?.revoke?.();
    mediaPlaybackCache.delete(key);
    const warmupEntry = driveWarmupCache.get(key);
    warmupEntry?.controller?.abort();
    driveWarmupCache.delete(key);
    driveWarmupErrors.delete(key);
    driveWarmupReady.delete(key);
    const preloadEntry = mediaAssetPreloadCache.get(key);
    disposeAssetPreload(preloadEntry);
    mediaAssetPreloadCache.delete(key);
  });
}

export function retainMediaPlayback(mediaList: ExerciseMediaRef[], storageAppId = currentStorageAppId()) {
  const activeStreamKeys = new Set(mediaList.map((media) => mediaCacheKey(media, storageAppId, 'stream')));
  const modes = ['blob', 'drive-warmup', 'asset-preload'];
  const allowedKeys = new Set(mediaList.flatMap((media) => modes.map((mode) => mediaCacheKey(media, storageAppId, mode))));
  mediaPlaybackCache.forEach((entry, key) => {
    if (key.startsWith('stream:')) {
      if (!activeStreamKeys.has(key)) entry.controller?.abort();
      return;
    }
    if (allowedKeys.has(key)) return;
    entry.controller?.abort();
    entry.resolution?.revoke?.();
    mediaPlaybackCache.delete(key);
  });
  driveWarmupCache.forEach((entry, key) => {
    if (allowedKeys.has(key)) return;
    entry.controller?.abort();
    driveWarmupCache.delete(key);
  });
  driveWarmupErrors.forEach((_detail, key) => {
    if (!allowedKeys.has(key)) driveWarmupErrors.delete(key);
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
  driveWarmupCache.forEach((entry) => entry.controller?.abort());
  driveWarmupCache.clear();
  driveWarmupErrors.clear();
  driveWarmupReady.clear();
  mediaAssetPreloadCache.forEach((entry) => disposeAssetPreload(entry));
  mediaAssetPreloadCache.clear();
}

export function latestMediaPlaybackError(media: ExerciseMediaRef, storageAppId = currentStorageAppId()) {
  return driveWarmupErrors.get(mediaCacheKey(media, storageAppId, 'drive-warmup')) || '';
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
  };
};

function driveLocalizationResolution(payload: DriveLocalizationPayload, media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, storageAppId: string): MediaPlaybackResolution | null {
  const status = String(payload.localization?.status || payload.status || '');
  const detail = String(payload.localization?.detail || payload.detail || payload.localization?.error || payload.error || '');
  if (payload.stream_url || status === 'ready' || status === 'localized') {
    return { status: 'ready', url: driveMediaStreamUrl(media, storageAppId), mediaKind: media.preview_kind, detail: '' };
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

function driveLocalizationBody(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>) {
  return {
    stable_storage_file_id: media.stable_storage_file_id,
    connection_id: media.connection_id,
    drive_file_id: media.drive_file_id,
    _app_secret_request: driveSecretRequest(media.connection_id)
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

export function driveSecretRequest(connectionId: string) {
  return {
    required: true,
    selectors: [
      { logical_names: ['google-drive-oauth-client-id', 'google-drive-oauth-client-secret'] },
      { logical_names: ['google-drive-refresh-token'], resource_type: 'drive_connection', resource_id: connectionId }
    ]
  };
}
