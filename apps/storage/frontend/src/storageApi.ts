import type { CatalogPayload, CreateFolderPayload, DeleteFilePayload, DeleteFolderPayload, DownloadFolderPayload, DriveCompleteOAuthPayload, DriveConnectionsPayload, DriveDisconnectPayload, DriveListPayload, DriveLocalizePayload, DrivePreviewPayload, DriveStartOAuthPayload, DriveWritePayload, FileRole, StorageFile, StorageFolder, StorageViewFilter, MoveFilePayload, MoveFolderPayload, MoveItemsPayload, PreviewTablePayload, PreviewTextPayload, ReadFilePayload, RenderPreviewPayload, UpdateMarkdownPayload, UploadFilePayload } from './types';
import { createRequestFingerprint, readThroughParentDataCache } from '@maverick/pwa-cache';
import { stableStorageFileSourceVersion } from './storageFileCacheClient';

const DEFAULT_APP_ID = 'storage';
const extensionContentTypes: Record<string, string> = {
  aac: 'audio/aac',
  flac: 'audio/flac',
  m4a: 'audio/mp4',
  mp3: 'audio/mpeg',
  oga: 'audio/ogg',
  ogg: 'audio/ogg',
  opus: 'audio/ogg',
  wav: 'audio/wav',
  weba: 'audio/webm'
};

function contentTypeForFile(file: File) {
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  if (!file.type || file.type === 'application/octet-stream') {
    return extensionContentTypes[extension] || 'application/octet-stream';
  }
  if (extension === 'm4a' && ['audio/x-m4a', 'audio/m4a', 'video/mp4'].includes(file.type.toLowerCase())) {
    return 'audio/mp4';
  }
  return file.type;
}

export type StorageApiOptions = {
  appId?: string;
  endpoint?: string;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
};

export type DriveUploadSessionStatusOptions = StorageApiOptions & {
  connectionId?: string;
  refreshRemote?: boolean;
};

export type UploadProgressPhase = 'starting' | 'reading' | 'uploading' | 'complete';

export type UploadProgress = {
  loaded: number;
  percent: number;
  phase: UploadProgressPhase;
  total: number;
};

export type UploadFileOptions = StorageApiOptions & {
  onProgress?: (progress: UploadProgress) => void;
};

export type DriveUploadTarget = {
  connectionId: string;
  driveFileId: string;
};

export type DriveListOptions = StorageApiOptions & {
  limit?: number;
  pageToken?: string;
};

export type DriveOAuthStartOptions = StorageApiOptions & {
  redirectUri?: string;
};

export type DriveOAuthCompleteOptions = {
  code: string;
  redirectUri: string;
  state: string;
};

export type DriveSyncPayload = {
  connection_id: string;
  memory_staleness?: unknown[];
  stale_storage_file_ids?: string[];
  sync_mode?: string;
  sync_state?: unknown;
  synced_files?: number;
};

export type DriveUploadSession = {
  id: string;
  status: 'uploading' | 'complete' | 'canceled' | 'error';
  provider: 'google_drive';
  connection_id: string;
  parent_drive_file_id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  bytes_uploaded: number;
  retry_count?: number;
  error?: string;
  progress?: {
    state?: string;
    bytes_completed?: number;
    bytes_total?: number;
  };
  file?: StorageFile | null;
};

export type DriveUploadSessionPayload = {
  status: 'uploading' | 'uploaded' | 'complete' | 'canceled' | 'error';
  provider: 'google_drive';
  connection_id: string;
  upload_session: DriveUploadSession;
  expected_offset?: number;
  file?: StorageFile;
};

export type LocalUploadSession = {
  id: string;
  status: 'uploading' | 'complete' | 'canceled' | 'error';
  provider: 'local';
  role: FileRole;
  folder_relative_path: string;
  relative_path: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  bytes_uploaded: number;
  error?: string;
  progress?: {
    state?: string;
    bytes_completed?: number;
    bytes_total?: number;
  };
  file?: StorageFile | null;
};

export type LocalUploadSessionPayload = {
  status: 'uploading' | 'uploaded' | 'complete' | 'canceled' | 'error';
  provider: 'local';
  upload_session: LocalUploadSession;
  expected_offset?: number;
  file?: StorageFile;
};

export type StorageMoveReference = {
  role: FileRole;
  relative_path: string;
  workspace_relative_path?: string;
};

export type StorageSecretRequest = {
  logical_names?: string[];
  required?: boolean;
  resource_id?: string;
  resource_type?: string;
  selectors?: Array<{
    logical_names: string[];
    resource_id?: string;
    resource_type?: string;
  }>;
};

const DRIVE_CLIENT_SECRET_NAMES = ['google-drive-oauth-client-id', 'google-drive-oauth-client-secret'];
const DRIVE_REFRESH_TOKEN_SECRET_NAME = 'google-drive-refresh-token';

export async function callBackend<T>(body: Record<string, unknown>, options: StorageApiOptions = {}): Promise<T> {
  const fetchImpl = options.fetchImpl || fetch;
  const requestInit: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withDefaultSecretRequest(body))
  };
  if (options.signal) {
    requestInit.signal = options.signal;
  }
  let response: Response;
  try {
    response = await fetchImpl(options.endpoint || storageBackendEndpoint(options.appId), requestInit);
  } catch (error) {
    if (options.signal?.aborted) throw error;
    const transport = new Error('Storage backend transport failed.', { cause: error });
    transport.name = 'MaverickTransportError';
    throw transport;
  }
  let payload: (T & { detail?: string; error?: string }) | null = null;
  try {
    payload = await response.json() as T & { detail?: string; error?: string };
  } catch (error) {
    if (response.ok) throw new TypeError('Storage returned an invalid JSON response.', { cause: error });
  }
  if (!response.ok) {
    throw new StorageHttpError(
      payload?.detail || payload?.error || 'Storage request failed',
      response.status,
      parseRetryAfter(response.headers.get('retry-after'))
    );
  }
  return payload as T;
}

export class StorageHttpError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfterMs: number | null) {
    super(message);
    this.name = 'MaverickHttpError';
  }
}

export function storageBackendEndpoint(appId = currentStorageAppId()): string {
  return `/api/apps/${encodeURIComponent(appId || DEFAULT_APP_ID)}/backend`;
}

export function currentStorageAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return DEFAULT_APP_ID;
  }
  try {
    return decodeURIComponent(match[1]) || DEFAULT_APP_ID;
  } catch {
    return match[1] || DEFAULT_APP_ID;
  }
}

export function decodeBase64(content: string, contentType: string) {
  const bytes = Uint8Array.from(atob(content), (char) => char.charCodeAt(0));
  return new Blob([bytes], { type: contentType });
}

export type CatalogRequest = Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>> & {
  file_ids?: string[];
  folder_path?: string;
  offset?: number;
  limit?: number;
  sync?: boolean;
  workspace_relative_paths?: string[];
};

export type CatalogReadOptions = Pick<StorageApiOptions, 'signal'>;
export const STORAGE_CATALOG_REVALIDATED_EVENT = 'maverick.storage.catalog-revalidated.v1';

export const CATALOG_PAGE_LIMIT = 500;
export const DRIVE_PAGE_LIMIT = 50;
export const MAX_BASE64_WRITE_BYTES = 25 * 1024 * 1024;
export const MAX_STORAGE_FILE_TRANSFER_BYTES = 500 * 1024 * 1024;
export const DRIVE_RESUMABLE_CHUNK_BYTES = 8 * 1024 * 1024;
export const LOCAL_UPLOAD_SESSION_CHUNK_BYTES = 8 * 1024 * 1024;

export async function loadCatalog(params: CatalogRequest = {}, options: CatalogReadOptions = {}) {
  if (params.sync === true || (params.offset ?? 0) > 0) {
    return callBackend<CatalogPayload>({ action: 'catalog', ...params }, options);
  }
  const canonical = canonicalCatalogRequest(params);
  const appId = currentStorageAppId();
  let entityId: string;
  try {
    entityId = await createRequestFingerprint(JSON.stringify(canonical));
  } catch {
    return callBackend<CatalogPayload>({ action: 'catalog', ...canonical }, { appId, signal: options.signal });
  }
  const result = await readThroughParentDataCache<CatalogPayload>({
    appId,
    entityId,
    resource: 'file-catalog',
    schemaRevision: 'storage.file-catalog.v1'
  }, async ({ knownRevision, signal }) => {
    const payload = await callBackend<CatalogPayload>({
      action: 'catalog',
      ...canonical,
      known_revision: knownRevision
    }, { appId, signal });
    if (payload.not_modified) {
      if (!knownRevision || payload.revision !== knownRevision) {
        throw new TypeError('Storage returned not_modified without the requested revision.');
      }
      return { kind: 'not_modified', revision: knownRevision } as const;
    }
    const sanitized = sanitizeCatalogPayload(payload);
    if (!sanitized) throw new TypeError('Storage returned an invalid catalog read model.');
    return { kind: 'value', payload: sanitized, revision: sanitized.revision } as const;
  }, { sanitize: sanitizeCatalogPayload, signal: options.signal });
  if (result.revalidation) {
    void result.revalidation.then((next) => {
      if (next.changed) dispatchCatalogRevalidated(entityId);
    }).catch(() => undefined);
  }
  return result.payload;
}

function canonicalCatalogRequest(params: CatalogRequest): CatalogRequest {
  return {
    query: String(params.query || ''),
    role: params.role || 'all',
    kind: params.kind || 'all',
    ...(params.folder_path === undefined ? {} : { folder_path: String(params.folder_path) }),
    offset: 0,
    ...(params.limit === undefined ? {} : { limit: params.limit }),
    ...(params.file_ids?.length ? { file_ids: [...params.file_ids].map(String).sort() } : {}),
    ...(params.workspace_relative_paths?.length
      ? { workspace_relative_paths: [...params.workspace_relative_paths].map(String).sort() }
      : {})
  };
}

export function sanitizeCatalogPayload(value: unknown): CatalogPayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const payload = value as Partial<CatalogPayload>;
  if (payload.schema !== 'storage.file-catalog.v1'
      || !/^[a-f0-9]{64}$/u.test(String(payload.revision || ''))
      || !payload.state || typeof payload.state !== 'object'
      || !Array.isArray(payload.files)
      || !Array.isArray(payload.folders)
      || !Array.isArray(payload.available_kinds)) return null;
  try {
    const sanitized = JSON.parse(JSON.stringify(payload, (key, item) => {
      const normalized = key.replace(/[^A-Za-z0-9]/gu, '').toLowerCase();
      if (normalized === 'weburl') return safeCatalogWebUrl(item);
      if (['authorizationurl', 'credential', 'credentials', 'downloadurl', 'localpath', 'remotelocator', 'signedurl', 'streamurl', 'token'].includes(normalized)
          || normalized.endsWith('token')
          || normalized.endsWith('secret')) return undefined;
      if (typeof item === 'string' && (/^blob\s*:/iu.test(item) || /[?&](?:sig|signature|x-amz-signature|x-goog-signature)=/iu.test(item))) {
        return undefined;
      }
      return item;
    })) as CatalogPayload;
    if (sanitized.inventory) {
      sanitized.inventory = { schema_version: String(sanitized.inventory.schema_version || '') };
    }
    if (!sanitized.files.every(validCatalogFile)
        || !sanitized.folders.every(validCatalogFolder)
        || !sanitized.available_kinds.every((kind) => typeof kind === 'string')) return null;
    return sanitized;
  } catch {
    return null;
  }
}

function validCatalogFile(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const file = value as { id?: unknown; file_id?: unknown };
  return (typeof file.id === 'string' && file.id.length > 0)
    || (typeof file.file_id === 'string' && file.file_id.length > 0);
}

function validCatalogFolder(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  return typeof (value as { id?: unknown }).id === 'string'
    && Boolean((value as { id: string }).id);
}

function safeCatalogWebUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password) return undefined;
    for (const key of url.searchParams.keys()) {
      const normalized = key.replace(/[^A-Za-z0-9]/gu, '').toLowerCase();
      if (['googleaccessid', 'sig', 'signature', 'xamzsignature', 'xgoogsignature'].includes(normalized)
          || normalized.endsWith('token')
          || normalized.endsWith('secret')) return undefined;
    }
    return url.toString();
  } catch {
    return undefined;
  }
}

function dispatchCatalogRevalidated(entityId: string) {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return;
  window.dispatchEvent(new CustomEvent(STORAGE_CATALOG_REVALIDATED_EVENT, { detail: { entityId } }));
}

export function loadViewFilter() {
  return callBackend<{ state: CatalogPayload['state'] }>({ action: 'view_filter' });
}

export function setViewFilter(filter: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>> & { preserve_custom?: boolean }) {
  return callBackend<{ state: CatalogPayload['state'] }>({ action: 'set_view_filter', ...filter });
}

export function setCustomView(view: Pick<StorageViewFilter, 'title' | 'file_ids' | 'workspace_relative_paths'> & Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>) {
  return callBackend<{ state: CatalogPayload['state'] }>({ action: 'set_custom_view', ...view });
}

export function clearCustomView() {
  return callBackend<{ state: CatalogPayload['state'] }>({ action: 'clear_custom_view' });
}

export function listDriveConnections(options: StorageApiOptions = {}) {
  return callBackend<DriveConnectionsPayload>({
    action: 'drive_connections.list',
    _app_secret_request: {}
  }, options);
}

export function startDriveOAuth(options: DriveOAuthStartOptions = {}) {
  const { redirectUri, ...apiOptions } = options;
  return callBackend<DriveStartOAuthPayload>({
    action: 'drive_connections.start_oauth',
    ...(redirectUri ? { redirect_uri: redirectUri } : {}),
    _app_secret_request: {
      logical_names: DRIVE_CLIENT_SECRET_NAMES,
      required: false
    } satisfies StorageSecretRequest
  }, apiOptions);
}

export async function completeDriveOAuth(oauth: DriveOAuthCompleteOptions, options: StorageApiOptions = {}) {
  const payload = await callBackend<DriveCompleteOAuthPayload>({
    action: 'drive_connections.complete_oauth',
    provider: 'google_drive',
    code: oauth.code,
    state: oauth.state,
    redirect_uri: oauth.redirectUri,
    _app_secret_request: {
      logical_names: DRIVE_CLIENT_SECRET_NAMES,
      required: true
    } satisfies StorageSecretRequest
  }, options);
  if (payload.status !== 'connected' || !payload.connection) {
    throw new Error('Google Drive connection failed. Check the Google Drive OAuth secret grants and start the connection again.');
  }
  return payload;
}

export function disconnectDriveConnection(connectionId: string, options: StorageApiOptions = {}) {
  return callBackend<DriveDisconnectPayload>({
    action: 'drive_connections.disconnect',
    connection_id: connectionId,
    _app_secret_request: {}
  }, options);
}

export function syncDriveConnection(connectionId: string, options: StorageApiOptions = {}) {
  return callBackend<DriveSyncPayload>({
    action: 'drive_sync',
    connection_id: connectionId,
    _app_secret_request: driveConnectionSecretRequest(connectionId)
  }, options);
}

export function listDriveRoots(connectionId: string, options: DriveListOptions = {}) {
  const { limit, pageToken, ...apiOptions } = options;
  return callBackend<DriveListPayload>({
    action: 'drive_list_roots',
    connection_id: connectionId,
    ...(limit === undefined ? {} : { limit }),
    ...(pageToken ? { page_token: pageToken } : {}),
    _app_secret_request: driveConnectionSecretRequest(connectionId)
  }, apiOptions);
}

export function listDriveChildren(connectionId: string, driveFileId: string, options: DriveListOptions = {}) {
  const { limit, pageToken, ...apiOptions } = options;
  return callBackend<DriveListPayload>({
    action: 'drive_list_children',
    connection_id: connectionId,
    drive_file_id: driveFileId,
    ...(limit === undefined ? {} : { limit }),
    ...(pageToken ? { page_token: pageToken } : {}),
    _app_secret_request: driveConnectionSecretRequest(connectionId)
  }, apiOptions);
}

export function readDriveFile(file: StorageFile, maxBytes: number, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<ReadFilePayload>({
    action: 'drive_read',
    ...locator,
    max_bytes: maxBytes,
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function previewDriveFile(file: StorageFile, maxBytes: number, maxChars?: number, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<DrivePreviewPayload>({
    action: 'drive_preview',
    ...locator,
    max_bytes: maxBytes,
    ...(maxChars === undefined ? {} : { max_chars: maxChars }),
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function localizeDriveFile(file: StorageFile, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<DriveLocalizePayload>({
    action: 'file.localize',
    ...locator,
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function driveLocalizationStatus(file: StorageFile, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<DriveLocalizePayload>({
    action: 'file.localize_status',
    ...locator,
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function retryDriveLocalization(file: StorageFile, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<DriveLocalizePayload>({
    action: 'file.localize_retry',
    ...locator,
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function cancelDriveLocalization(file: StorageFile, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<DriveLocalizePayload>({
    action: 'file.localize_cancel',
    ...locator,
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function reconcileFile(file?: StorageFile, options: StorageApiOptions = {}) {
  if (file?.provider === 'google_drive') {
    const locator = driveFileLocator(file);
    return callBackend<{ status: 'reconciled'; file?: StorageFile; files?: StorageFile[] }>({
      action: 'file.reconcile',
      ...locator,
      _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
    }, options);
  }
  return callBackend<{ status: 'reconciled'; file?: StorageFile; files?: StorageFile[] }>({
    action: 'file.reconcile',
    ...(file?.file_id ? { file_id: file.file_id } : {}),
    _app_secret_request: {}
  }, options);
}

export function driveMediaDownloadUrl(payload: Pick<DriveLocalizePayload, 'download_url' | 'stream_url'>) {
  if (payload.download_url) return payload.download_url;
  return `${payload.stream_url}${payload.stream_url.includes('?') ? '&' : '?'}download=1`;
}

export function storageMediaStreamUrl(file: StorageFile, options: { appId?: string; download?: boolean } = {}) {
  const params = new URLSearchParams();
  params.set('stable_storage_file_id', file.file_id || file.id);
  const sourceVersion = stableStorageFileSourceVersion(file);
  if (sourceVersion) params.set('source_version', sourceVersion);
  if (file.provider === 'google_drive') {
    const locator = driveFileLocator(file);
    params.set('stable_storage_file_id', locator.stable_storage_file_id || file.id);
    params.set('connection_id', locator.connection_id);
    params.set('drive_file_id', locator.drive_file_id);
    const localizationId = String(file.localization_id || '').trim();
    if (localizationId) params.set('localization_id', localizationId);
    params.set('_app_secret_request', JSON.stringify(driveConnectionSecretRequest(locator.connection_id)));
  } else {
    params.set('_app_secret_request', JSON.stringify({ logical_names: [], required: false }));
  }
  if (options.download) params.set('download', '1');
  return `/api/apps/${encodeURIComponent(options.appId || currentStorageAppId())}/media?${params.toString()}`;
}

export function driveMediaStreamUrl(file: StorageFile, options: { appId?: string; download?: boolean } = {}) {
  return storageMediaStreamUrl(file, options);
}

export function folderMediaDownloadUrl(folder: StorageFolder, options: { appId?: string } = {}) {
  const params = new URLSearchParams();
  params.set('media_kind', 'folder');
  params.set('role', folder.role);
  params.set('relative_path', folder.relative_path);
  params.set('download', '1');
  params.set('_app_secret_request', JSON.stringify({ logical_names: [], required: false }));
  return `/api/apps/${encodeURIComponent(options.appId || currentStorageAppId())}/media?${params.toString()}`;
}

export function renameDriveFile(file: StorageFile, newName: string, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<{ file: StorageFile }>({
    action: 'drive_rename',
    ...locator,
    new_name: newName,
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export function trashDriveFile(file: StorageFile, options: StorageApiOptions = {}) {
  const locator = driveFileLocator(file);
  return callBackend<{ file: StorageFile; status: string }>({
    action: 'drive_trash',
    ...locator,
    confirm: true,
    delete_policy: 'user_confirmed',
    _app_secret_request: driveConnectionSecretRequest(locator.connection_id)
  }, options);
}

export async function createFolder(role: FileRole, parentRelativePath: string, folderName: string) {
  return callBackend<CreateFolderPayload>({
    action: 'create_folder',
    role,
    parent_relative_path: parentRelativePath,
    folder_name: folderName
  });
}

export async function uploadFile(role: FileRole, folderRelativePath: string, file: File, options: UploadFileOptions = {}) {
  assertStorageTransferSize(file);
  if (file.size > MAX_BASE64_WRITE_BYTES) {
    return uploadLocalFileChunked(role, folderRelativePath, file, options);
  }
  assertBase64WriteSize(file);
  const contentBase64 = await fileToBase64(file, (loaded, total) => {
    const percent = total > 0 ? Math.round((loaded / total) * 35) : 0;
    options.onProgress?.({ loaded, percent: Math.min(35, percent), phase: 'reading', total });
  });
  const body = {
    action: 'upload_file',
    role,
    folder_relative_path: folderRelativePath,
    file_name: file.name,
    content_base64: contentBase64,
    content_type: contentTypeForFile(file)
  };
  options.onProgress?.({ loaded: 0, percent: 35, phase: 'uploading', total: file.size });
  const useProgressRequest = Boolean(options.onProgress) && typeof XMLHttpRequest !== 'undefined' && !options.fetchImpl;
  const payload = useProgressRequest
    ? await callBackendWithUploadProgress<UploadFilePayload>(body, options)
    : await callBackend<UploadFilePayload>(body, options);
  options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
  return payload;
}

async function uploadLocalFileChunked(role: FileRole, folderRelativePath: string, file: File, options: UploadFileOptions): Promise<UploadFilePayload> {
  assertNotAborted(options.signal);
  options.onProgress?.({ loaded: 0, percent: 0, phase: 'starting', total: file.size });
  const started = await startLocalUploadSession(role, folderRelativePath, file, options);
  let session = started.upload_session;
  let offset = Math.max(0, session.bytes_uploaded || 0);
  try {
    while (offset < file.size) {
      assertNotAborted(options.signal);
      const nextOffset = Math.min(file.size, offset + LOCAL_UPLOAD_SESSION_CHUNK_BYTES);
      const contentBase64 = await blobToBase64(file.slice(offset, nextOffset));
      let attempt = 0;
      while (true) {
        try {
          const payload = await uploadLocalSessionChunk(session.id, offset, contentBase64, options);
          session = payload.upload_session;
          offset = payload.expected_offset ?? session.bytes_uploaded ?? nextOffset;
          options.onProgress?.({
            loaded: offset,
            percent: file.size > 0 ? Math.min(99, Math.round((offset / file.size) * 100)) : 99,
            phase: 'uploading',
            total: file.size
          });
          if (payload.file || session.file) {
            options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
            return { file: (payload.file || session.file) as StorageFile, bytes_written: file.size };
          }
          break;
        } catch (error) {
          assertNotAborted(options.signal);
          attempt += 1;
          if (attempt > 3) throw error;
          await delay(250 * (2 ** (attempt - 1)));
          const refreshed = await localUploadSessionStatus(session.id, options);
          session = refreshed.upload_session;
          const completedFile = refreshed.file || session.file;
          if (completedFile) {
            options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
            return { file: completedFile as StorageFile, bytes_written: file.size };
          }
          const refreshedOffset = Math.max(offset, session.bytes_uploaded || 0);
          if (refreshedOffset > offset) {
            offset = refreshedOffset;
            options.onProgress?.({
              loaded: offset,
              percent: file.size > 0 ? Math.min(99, Math.round((offset / file.size) * 100)) : 99,
              phase: 'uploading',
              total: file.size
            });
            break;
          }
          offset = refreshedOffset;
        }
      }
    }
  } catch (error) {
    if (options.signal?.aborted && session?.id) {
      await cancelLocalUploadSession(session.id, { ...options, signal: undefined }).catch(() => undefined);
    }
    throw error;
  }
  const refreshed = await localUploadSessionStatus(session.id, options);
  const completedFile = refreshed.file || refreshed.upload_session.file;
  if (!completedFile) {
    throw new Error('Storage upload did not return the uploaded file metadata.');
  }
  options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
  return { file: completedFile, bytes_written: file.size };
}

function startLocalUploadSession(role: FileRole, folderRelativePath: string, file: File, options: StorageApiOptions = {}) {
  return callBackend<LocalUploadSessionPayload>({
    action: 'local_upload_session.start',
    role,
    folder_relative_path: folderRelativePath,
    file_name: file.name,
    content_type: contentTypeForFile(file),
    size_bytes: file.size
  }, options);
}

function uploadLocalSessionChunk(sessionId: string, offset: number, contentBase64: string, options: StorageApiOptions = {}) {
  return callBackend<LocalUploadSessionPayload>({
    action: 'local_upload_session.chunk',
    local_upload_session_id: sessionId,
    chunk_offset: offset,
    content_base64: contentBase64
  }, options);
}

export function localUploadSessionStatus(sessionId: string, options: StorageApiOptions = {}) {
  return callBackend<LocalUploadSessionPayload>({
    action: 'local_upload_session.status',
    local_upload_session_id: sessionId
  }, options);
}

export function cancelLocalUploadSession(sessionId: string, options: StorageApiOptions = {}) {
  return callBackend<LocalUploadSessionPayload>({
    action: 'local_upload_session.cancel',
    local_upload_session_id: sessionId
  }, options);
}

export async function uploadDriveFile(file: File, target: DriveUploadTarget, options: UploadFileOptions = {}) {
  const connectionId = target.connectionId.trim();
  const parentDriveFileId = target.driveFileId.trim();
  if (!connectionId || !parentDriveFileId) {
    throw new Error('Choose a Google Drive folder before uploading a file.');
  }
  if (file.size > MAX_BASE64_WRITE_BYTES) {
    return uploadDriveFileResumable(file, { connectionId, driveFileId: parentDriveFileId }, options);
  }
  assertBase64WriteSize(file);
  const contentBase64 = await fileToBase64(file, (loaded, total) => {
    const percent = total > 0 ? Math.round((loaded / total) * 35) : 0;
    options.onProgress?.({ loaded, percent: Math.min(35, percent), phase: 'reading', total });
  });
  const body = {
    action: 'drive_write',
    connection_id: connectionId,
    parent_drive_file_id: parentDriveFileId,
    file_name: file.name,
    content_base64: contentBase64,
    content_type: contentTypeForFile(file),
    _app_secret_request: driveConnectionSecretRequest(connectionId)
  };
  options.onProgress?.({ loaded: 0, percent: 35, phase: 'uploading', total: file.size });
  const useProgressRequest = Boolean(options.onProgress) && typeof XMLHttpRequest !== 'undefined' && !options.fetchImpl;
  const payload = useProgressRequest
    ? await callBackendWithUploadProgress<DriveWritePayload>(body, options)
    : await callBackend<DriveWritePayload>(body, options);
  options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
  return payload;
}

async function uploadDriveFileResumable(file: File, target: DriveUploadTarget, options: UploadFileOptions): Promise<DriveWritePayload> {
  const connectionId = target.connectionId.trim();
  const parentDriveFileId = target.driveFileId.trim();
  assertNotAborted(options.signal);
  options.onProgress?.({ loaded: 0, percent: 0, phase: 'starting', total: file.size });
  const started = await startDriveUploadSession(file, { connectionId, driveFileId: parentDriveFileId }, options);
  let session = started.upload_session;
  let offset = Math.max(0, session.bytes_uploaded || 0);
  try {
    while (offset < file.size) {
      assertNotAborted(options.signal);
      const nextOffset = Math.min(file.size, offset + DRIVE_RESUMABLE_CHUNK_BYTES);
      const contentBase64 = await blobToBase64(file.slice(offset, nextOffset));
      let attempt = 0;
      while (true) {
        try {
          const payload = await uploadDriveSessionChunk(session.id, offset, contentBase64, connectionId, options);
          session = payload.upload_session;
          offset = payload.expected_offset ?? session.bytes_uploaded ?? nextOffset;
          options.onProgress?.({
            loaded: offset,
            percent: file.size > 0 ? Math.min(99, Math.round((offset / file.size) * 100)) : 99,
            phase: 'uploading',
            total: file.size
          });
          if (payload.file || session.file) {
            options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
            return {
              connection_id: connectionId,
              file: (payload.file || session.file) as StorageFile,
              provider: 'google_drive',
              status: 'uploaded'
            };
          }
          break;
        } catch (error) {
          assertNotAborted(options.signal);
          attempt += 1;
          if (attempt > 3) throw error;
          await delay(250 * (2 ** (attempt - 1)));
          const refreshed = await driveUploadSessionStatus(session.id, { ...options, connectionId, refreshRemote: true });
          session = refreshed.upload_session;
          const completedFile = refreshed.file || session.file;
          if (completedFile) {
            options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
            return {
              connection_id: connectionId,
              file: completedFile as StorageFile,
              provider: 'google_drive',
              status: 'uploaded'
            };
          }
          const refreshedOffset = Math.max(offset, session.bytes_uploaded || 0);
          if (refreshedOffset > offset) {
            offset = refreshedOffset;
            options.onProgress?.({
              loaded: offset,
              percent: file.size > 0 ? Math.min(99, Math.round((offset / file.size) * 100)) : 99,
              phase: 'uploading',
              total: file.size
            });
            break;
          }
          offset = refreshedOffset;
        }
      }
    }
  } catch (error) {
    if (options.signal?.aborted && session?.id) {
      await cancelDriveUploadSession(session.id, { ...options, connectionId, signal: undefined }).catch(() => undefined);
    }
    throw error;
  }
  const refreshed = await driveUploadSessionStatus(session.id, { ...options, connectionId, refreshRemote: true });
  const completedFile = refreshed.file || refreshed.upload_session.file;
  if (!completedFile) {
    throw new Error('Google Drive upload did not return the uploaded file metadata.');
  }
  options.onProgress?.({ loaded: file.size, percent: 100, phase: 'complete', total: file.size });
  return { connection_id: connectionId, file: completedFile, provider: 'google_drive', status: 'uploaded' };
}

function startDriveUploadSession(file: File, target: DriveUploadTarget, options: StorageApiOptions = {}) {
  return callBackend<DriveUploadSessionPayload>({
    action: 'drive_upload_session.start',
    connection_id: target.connectionId,
    parent_drive_file_id: target.driveFileId,
    file_name: file.name,
    content_type: contentTypeForFile(file),
    size_bytes: file.size,
    _app_secret_request: driveConnectionSecretRequest(target.connectionId)
  }, options);
}

function uploadDriveSessionChunk(sessionId: string, offset: number, contentBase64: string, connectionId: string, options: StorageApiOptions = {}) {
  return callBackend<DriveUploadSessionPayload>({
    action: 'drive_upload_session.chunk',
    drive_upload_session_id: sessionId,
    chunk_offset: offset,
    content_base64: contentBase64,
    _app_secret_request: driveConnectionSecretRequest(connectionId)
  }, options);
}

export function driveUploadSessionStatus(sessionId: string, options: DriveUploadSessionStatusOptions = {}) {
  const { connectionId, refreshRemote, ...apiOptions } = options;
  const body: Record<string, unknown> = {
    action: 'drive_upload_session.status',
    drive_upload_session_id: sessionId,
    refresh_remote: Boolean(refreshRemote),
    _app_secret_request: connectionId ? driveConnectionSecretRequest(connectionId) : {}
  };
  if (connectionId) {
    body.connection_id = connectionId;
  }
  return callBackend<DriveUploadSessionPayload>(body, apiOptions);
}

export function cancelDriveUploadSession(sessionId: string, options: StorageApiOptions & { connectionId?: string } = {}) {
  const { connectionId, ...apiOptions } = options;
  return callBackend<DriveUploadSessionPayload>({
    action: 'drive_upload_session.cancel',
    drive_upload_session_id: sessionId,
    _app_secret_request: connectionId ? driveConnectionSecretRequest(connectionId) : {}
  }, apiOptions);
}

export async function readFile(file: StorageFile, maxBytes: number) {
  return callBackend<ReadFilePayload>({
    action: 'read_file',
    role: file.role,
    relative_path: file.relative_path,
    max_bytes: maxBytes
  });
}

export async function readPreviewText(file: StorageFile, maxChars?: number) {
  return callBackend<PreviewTextPayload>({
    action: 'preview_text',
    role: file.role,
    relative_path: file.relative_path,
    ...(maxChars === undefined ? {} : { max_chars: maxChars })
  });
}

export async function readPreviewTable(file: StorageFile, maxRows?: number, maxColumns?: number) {
  return callBackend<PreviewTablePayload>({
    action: 'preview_table',
    role: file.role,
    relative_path: file.relative_path,
    ...(maxRows === undefined ? {} : { max_rows: maxRows }),
    ...(maxColumns === undefined ? {} : { max_columns: maxColumns })
  });
}

export async function renderPreview(file: StorageFile) {
  return callBackend<RenderPreviewPayload>({
    action: 'render_preview',
    role: file.role,
    relative_path: file.relative_path
  });
}

export async function renderThumbnail(file: StorageFile) {
  return callBackend<RenderPreviewPayload>({
    action: 'render_thumbnail',
    role: file.role,
    relative_path: file.relative_path
  });
}

export async function renameFile(file: StorageFile, newName: string) {
  return callBackend<{ file: StorageFile }>({
    action: 'rename_file',
    role: file.role,
    relative_path: file.relative_path,
    new_name: newName
  });
}

export async function deleteFile(file: StorageFile) {
  return callBackend<DeleteFilePayload>({
    action: 'delete_file',
    role: file.role,
    relative_path: file.relative_path
  });
}

export async function downloadFolder(folder: StorageFolder) {
  return callBackend<DownloadFolderPayload>({
    action: 'download_folder',
    role: folder.role,
    relative_path: folder.relative_path
  });
}

export async function deleteFolder(folder: StorageFolder) {
  return callBackend<DeleteFolderPayload>({
    action: 'delete_folder',
    role: folder.role,
    relative_path: folder.relative_path
  });
}

export async function updateMarkdownFile(file: StorageFile, content: string) {
  return callBackend<UpdateMarkdownPayload>({
    action: 'update_markdown_file',
    role: file.role,
    relative_path: file.relative_path,
    content
  });
}

export async function moveFile(file: StorageFile, targetFolderRelativePath: string) {
  return moveFileReference(file, targetFolderRelativePath);
}

export async function moveFileReference(file: Pick<StorageFile, 'role' | 'relative_path'>, targetFolderRelativePath: string) {
  return callBackend<MoveFilePayload>({
    action: 'move_file',
    role: file.role,
    relative_path: file.relative_path,
    target_folder_relative_path: targetFolderRelativePath
  });
}

export async function moveFolder(folder: StorageFolder, targetFolderRelativePath: string) {
  return moveFolderReference(folder, targetFolderRelativePath);
}

export async function moveFolderReference(folder: Pick<StorageFolder, 'role' | 'relative_path'>, targetFolderRelativePath: string) {
  return callBackend<MoveFolderPayload>({
    action: 'move_folder',
    role: folder.role,
    relative_path: folder.relative_path,
    target_folder_relative_path: targetFolderRelativePath
  });
}

export async function moveItemsReferences(files: StorageMoveReference[], folders: StorageMoveReference[], role: FileRole, targetFolderRelativePath: string) {
  return callBackend<MoveItemsPayload>({
    action: 'move_items',
    role,
    target_folder_relative_path: targetFolderRelativePath,
    files: files.map(moveReferencePayload),
    folders: folders.map(moveReferencePayload)
  });
}

function moveReferencePayload(item: StorageMoveReference) {
  return {
    role: item.role,
    relative_path: item.relative_path,
    ...(item.workspace_relative_path ? { workspace_relative_path: item.workspace_relative_path } : {})
  };
}

function assertBase64WriteSize(file: File) {
  if (file.size <= MAX_BASE64_WRITE_BYTES) {
    return;
  }
  throw new Error(`Storage uploads through this path are limited to ${Math.floor(MAX_BASE64_WRITE_BYTES / (1024 * 1024))} MB.`);
}

function assertStorageTransferSize(file: File) {
  if (file.size <= MAX_STORAGE_FILE_TRANSFER_BYTES) {
    return;
  }
  throw new Error(`Storage uploads are limited to ${Math.floor(MAX_STORAGE_FILE_TRANSFER_BYTES / (1024 * 1024))} MB.`);
}

function callBackendWithUploadProgress<T>(body: Record<string, unknown>, options: UploadFileOptions): Promise<T> {
  const endpoint = options.endpoint || storageBackendEndpoint(options.appId);
  const serializedBody = JSON.stringify(withDefaultSecretRequest(body));
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const abortRequest = () => request.abort();
    request.open('POST', endpoint);
    request.setRequestHeader('Content-Type', 'application/json');
    if (options.signal) {
      if (options.signal.aborted) {
        reject(new DOMException('Upload canceled.', 'AbortError'));
        return;
      }
      options.signal.addEventListener('abort', abortRequest, { once: true });
    }
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const uploadPercent = event.total > 0 ? event.loaded / event.total : 0;
      options.onProgress?.({
        loaded: event.loaded,
        percent: Math.min(98, 35 + Math.round(uploadPercent * 63)),
        phase: 'uploading',
        total: event.total
      });
    };
    request.onerror = () => reject(new Error('Storage request failed'));
    request.onabort = () => reject(new DOMException('Upload canceled.', 'AbortError'));
    request.onload = () => {
      options.signal?.removeEventListener('abort', abortRequest);
      let payload: unknown = {};
      try {
        payload = request.responseText ? JSON.parse(request.responseText) : {};
      } catch {
        reject(new Error('Storage response was not valid JSON'));
        return;
      }
      if (request.status < 200 || request.status >= 300) {
        const errorPayload = payload as { detail?: string; error?: string };
        reject(new Error(errorPayload.detail || errorPayload.error || 'Storage request failed'));
        return;
      }
      resolve(payload as T);
    };
    request.send(serializedBody);
  });
}

function withDefaultSecretRequest(body: Record<string, unknown>) {
  const explicitRequest = body._app_secret_request;
  if (explicitRequest && typeof explicitRequest === 'object' && !Array.isArray(explicitRequest)) {
    return body;
  }
  return {
    ...body,
    _app_secret_request: {
      logical_names: [],
      required: false
    } satisfies StorageSecretRequest
  };
}

export function driveConnectionSecretRequest(connectionId: string): StorageSecretRequest {
  return {
    required: true,
    selectors: [
      { logical_names: DRIVE_CLIENT_SECRET_NAMES },
      {
        logical_names: [DRIVE_REFRESH_TOKEN_SECRET_NAME],
        resource_type: 'drive_connection',
        resource_id: connectionId
      }
    ]
  };
}

function driveFileLocator(file: StorageFile) {
  const connectionId = String(file.connection_id || '').trim();
  const driveFileId = String(file.drive_file_id || '').trim();
  const stableStorageFileId = String(file.file_id || file.id || '').trim();
  if (!connectionId || !driveFileId) {
    throw new Error('Google Drive file identity is missing.');
  }
  return {
    connection_id: connectionId,
    drive_file_id: driveFileId,
    ...(stableStorageFileId ? { stable_storage_file_id: stableStorageFileId } : {})
  };
}

function fileToBase64(file: File, onProgress?: (loaded: number, total: number) => void) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Unable to read selected file.'));
    reader.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(event.loaded, event.total);
      }
    };
    reader.onload = () => {
      const result = String(reader.result || '');
      const separatorIndex = result.indexOf(',');
      onProgress?.(file.size, file.size);
      resolve(separatorIndex >= 0 ? result.slice(separatorIndex + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  const batchSize = 0x8000;
  for (let index = 0; index < bytes.length; index += batchSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + batchSize));
  }
  return btoa(binary);
}

function assertNotAborted(signal?: AbortSignal) {
  if (!signal?.aborted) return;
  throw new DOMException('Upload canceled.', 'AbortError');
}

function delay(milliseconds: number) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1_000, 60_000);
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, Math.min(timestamp - Date.now(), 60_000)) : null;
}
