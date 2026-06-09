import { callStorageBackend, currentStorageAppId } from './api';
import type { ExerciseMediaRef, MediaPlaybackResolution } from './types';

const LOCAL_BLOB_FALLBACK_MAX_BYTES = 25 * 1024 * 1024;

export function initialMediaResolution(): MediaPlaybackResolution {
  return { status: 'idle', url: '', mediaKind: 'none', detail: '' };
}

export async function resolveMediaPlayback(media: ExerciseMediaRef | null, storageAppId = currentStorageAppId()): Promise<MediaPlaybackResolution> {
  if (!media) {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Questo segmento non ha media Storage riproducibili.' };
  }
  if (media.preview_kind !== 'image' && media.preview_kind !== 'video') {
    return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Questo file non e riproducibile nella Work mode V1.' };
  }
  if (media.kind === 'local_file') {
    if (!media.file_id) {
      return { status: 'blocked', url: '', mediaKind: 'none', detail: 'Il media locale non ha un file_id Storage stabile.' };
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
  try {
    const payload = await callStorageBackend<{ status?: string; stream_url?: string; localization?: Record<string, unknown>; detail?: string }>(
      {
        action: 'file.localize',
        stable_storage_file_id: media.stable_storage_file_id,
        connection_id: media.connection_id,
        drive_file_id: media.drive_file_id,
        _app_secret_request: driveSecretRequest(media.connection_id)
      },
      storageAppId
    );
    if (payload.stream_url) {
      return { status: 'ready', url: payload.stream_url, mediaKind: media.preview_kind, detail: '' };
    }
    return {
      status: 'localizing',
      url: driveMediaStreamUrl(media, storageAppId),
      mediaKind: media.preview_kind,
      detail: String(payload.localization?.status || payload.status || 'Storage sta preparando il media Drive.'),
      canRetry: Boolean(payload.localization?.can_retry),
      canCancel: Boolean(payload.localization?.can_cancel)
    };
  } catch (error) {
    return {
      status: 'error',
      url: driveMediaStreamUrl(media, storageAppId),
      mediaKind: media.preview_kind,
      detail: error instanceof Error ? error.message : 'Storage non riesce a preparare questo video Drive per la riproduzione.',
      canRetry: true
    };
  }
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
      detail: 'Questo file non puo essere riprodotto con il fallback bounded. Aprilo in Storage o usa un media stream Storage.'
    };
  }
  const payload = await callStorageBackend<{ content_base64: string; file?: { content_type?: string } }>(
    { action: 'file.content.read', workspace_relative_path: media.workspace_relative_path, max_bytes: LOCAL_BLOB_FALLBACK_MAX_BYTES },
    storageAppId
  );
  const binary = Uint8Array.from(atob(payload.content_base64), (char) => char.charCodeAt(0));
  const blob = new Blob([binary], { type: payload.file?.content_type || media.content_type || 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  return { status: 'ready', url, mediaKind: media.preview_kind, detail: '', revoke: () => URL.revokeObjectURL(url) };
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

export function driveSecretRequest(connectionId: string) {
  return {
    required: true,
    selectors: [
      { logical_names: ['google-drive-oauth-client-id', 'google-drive-oauth-client-secret'] },
      { logical_names: ['google-drive-refresh-token'], resource_type: 'drive_connection', resource_id: connectionId }
    ]
  };
}
