import type { StorageFile } from '@/types';

export type FileSortKey = 'date' | 'size' | 'type' | 'name';

export function catalogSort(sortKey: FileSortKey) {
  const fields = { date: 'created_at', size: 'size_bytes', type: 'preview_kind', name: 'name' } as const;
  return { sort_by: fields[sortKey], sort_direction: sortKey === 'name' || sortKey === 'type' ? 'asc' as const : 'desc' as const };
}

export function sortStorageFiles(files: StorageFile[], sortKey: FileSortKey) {
  return [...files].sort((left, right) => compareStorageFiles(left, right, sortKey));
}

function compareStorageFiles(left: StorageFile, right: StorageFile, sortKey: FileSortKey) {
  if (sortKey === 'date') {
    const result = storageFileTimestamp(right) - storageFileTimestamp(left);
    if (result !== 0) return result;
  } else if (sortKey === 'size') {
    const result = right.size_bytes - left.size_bytes;
    if (result !== 0) return result;
  } else if (sortKey === 'type') {
    const typeResult = compareText(left.preview_kind, right.preview_kind) || compareText(left.extension, right.extension);
    if (typeResult !== 0) return typeResult;
  }
  return compareText(left.name, right.name) || compareText(left.workspace_relative_path, right.workspace_relative_path);
}

function storageFileTimestamp(file: StorageFile) {
  const timestamp = file.created_at || file.modified_at;
  const value = timestamp ? new Date(timestamp).getTime() : 0;
  return Number.isFinite(value) ? value : 0;
}

function compareText(left: string, right: string) {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' });
}
