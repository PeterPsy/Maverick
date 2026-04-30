import type { CatalogPayload, CreateFolderPayload, DeleteFilePayload, FileRole, GalleryFile, GalleryViewFilter, MoveFilePayload, PreviewTablePayload, PreviewTextPayload, ReadFilePayload, RenderPreviewPayload, UpdateMarkdownPayload, UploadFilePayload } from './types';

export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/gallery/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || payload.error || 'Gallery request failed');
  return payload as T;
}

export function decodeBase64(content: string, contentType: string) {
  const bytes = Uint8Array.from(atob(content), (char) => char.charCodeAt(0));
  return new Blob([bytes], { type: contentType });
}

export function loadCatalog() {
  return callBackend<CatalogPayload>({ action: 'catalog' });
}

export function loadViewFilter() {
  return callBackend<{ state: CatalogPayload['state'] }>({ action: 'view_filter' });
}

export function setViewFilter(filter: Partial<Pick<GalleryViewFilter, 'query' | 'role' | 'kind'>> & { preserve_custom?: boolean }) {
  return callBackend<{ state: CatalogPayload['state'] }>({ action: 'set_view_filter', ...filter });
}

export function setCustomView(view: Pick<GalleryViewFilter, 'title' | 'file_ids' | 'workspace_relative_paths'> & Partial<Pick<GalleryViewFilter, 'query' | 'role' | 'kind'>>) {
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

export async function readFile(file: GalleryFile, maxBytes: number) {
  return callBackend<ReadFilePayload>({
    action: 'read_file',
    role: file.role,
    relative_path: file.relative_path,
    max_bytes: maxBytes
  });
}

export async function readPreviewText(file: GalleryFile, maxChars?: number) {
  return callBackend<PreviewTextPayload>({
    action: 'preview_text',
    role: file.role,
    relative_path: file.relative_path,
    ...(maxChars === undefined ? {} : { max_chars: maxChars })
  });
}

export async function readPreviewTable(file: GalleryFile, maxRows?: number, maxColumns?: number) {
  return callBackend<PreviewTablePayload>({
    action: 'preview_table',
    role: file.role,
    relative_path: file.relative_path,
    ...(maxRows === undefined ? {} : { max_rows: maxRows }),
    ...(maxColumns === undefined ? {} : { max_columns: maxColumns })
  });
}

export async function renderPreview(file: GalleryFile) {
  return callBackend<RenderPreviewPayload>({
    action: 'render_preview',
    role: file.role,
    relative_path: file.relative_path
  });
}

export async function renderThumbnail(file: GalleryFile) {
  return callBackend<RenderPreviewPayload>({
    action: 'render_thumbnail',
    role: file.role,
    relative_path: file.relative_path
  });
}

export async function renameFile(file: GalleryFile, newName: string) {
  return callBackend<{ file: GalleryFile }>({
    action: 'rename_file',
    role: file.role,
    relative_path: file.relative_path,
    new_name: newName
  });
}

export async function deleteFile(file: GalleryFile) {
  return callBackend<DeleteFilePayload>({
    action: 'delete_file',
    role: file.role,
    relative_path: file.relative_path
  });
}

export async function updateMarkdownFile(file: GalleryFile, content: string) {
  return callBackend<UpdateMarkdownPayload>({
    action: 'update_markdown_file',
    role: file.role,
    relative_path: file.relative_path,
    content
  });
}

export async function moveFile(file: GalleryFile, targetFolderRelativePath: string) {
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
