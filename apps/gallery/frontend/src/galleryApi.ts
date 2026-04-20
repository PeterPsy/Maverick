import type { CatalogPayload, GalleryFile, ReadFilePayload } from './types';

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

export async function readFile(file: GalleryFile, maxBytes: number) {
  return callBackend<ReadFilePayload>({
    action: 'read_file',
    role: file.role,
    relative_path: file.relative_path,
    max_bytes: maxBytes
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

