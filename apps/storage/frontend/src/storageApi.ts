import type { CatalogPayload, CreateFolderPayload, DeleteFilePayload, DeleteFolderPayload, DownloadFolderPayload, FileRole, StorageFile, StorageFolder, StorageViewFilter, MoveFilePayload, PreviewTablePayload, PreviewTextPayload, ReadFilePayload, RenderPreviewPayload, UpdateMarkdownPayload, UploadFilePayload } from './types';

const DEFAULT_APP_ID = 'storage';

export type StorageApiOptions = {
  appId?: string;
  endpoint?: string;
  fetchImpl?: typeof fetch;
};

export async function callBackend<T>(body: Record<string, unknown>, options: StorageApiOptions = {}): Promise<T> {
  const fetchImpl = options.fetchImpl || fetch;
  const response = await fetchImpl(options.endpoint || storageBackendEndpoint(options.appId), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || payload.error || 'Storage request failed');
  return payload as T;
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

export const CATALOG_PAGE_LIMIT = 500;

export function loadCatalog(params: CatalogRequest = {}) {
  return callBackend<CatalogPayload>({ action: 'catalog', ...params });
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

export async function createFolder(role: FileRole, parentRelativePath: string, folderName: string) {
  return callBackend<CreateFolderPayload>({
    action: 'create_folder',
    role,
    parent_relative_path: parentRelativePath,
    folder_name: folderName
  });
}

export async function uploadFile(role: FileRole, folderRelativePath: string, file: File) {
  return callBackend<UploadFilePayload>({
    action: 'upload_file',
    role,
    folder_relative_path: folderRelativePath,
    file_name: file.name,
    content_base64: await fileToBase64(file)
  });
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

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Unable to read selected file.'));
    reader.onload = () => {
      const result = String(reader.result || '');
      const separatorIndex = result.indexOf(',');
      resolve(separatorIndex >= 0 ? result.slice(separatorIndex + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}
