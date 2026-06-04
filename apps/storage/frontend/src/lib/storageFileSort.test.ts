import { describe, expect, it } from 'vitest';
import { sortStorageFiles, type FileSortKey } from './storageFileSort';
import type { PreviewKind, StorageFile } from '@/types';

describe('sortStorageFiles', () => {
  it('sorts by creation date descending with modified date fallback', () => {
    expect(sortIds('date', [
      file({ id: 'old', created_at: '2026-06-01T12:00:00Z', modified_at: '2026-06-01T12:00:00Z' }),
      file({ id: 'fallback', created_at: '', modified_at: '2026-06-03T12:00:00Z' }),
      file({ id: 'new', created_at: '2026-06-04T12:00:00Z', modified_at: '2026-06-04T12:00:00Z' }),
    ])).toEqual(['new', 'fallback', 'old']);
  });

  it('sorts by size descending', () => {
    expect(sortIds('size', [
      file({ id: 'small', size_bytes: 10 }),
      file({ id: 'large', size_bytes: 300 }),
      file({ id: 'medium', size_bytes: 120 }),
    ])).toEqual(['large', 'medium', 'small']);
  });

  it('sorts by file type then name', () => {
    expect(sortIds('type', [
      file({ id: 'text-b', name: 'beta.txt', preview_kind: 'text', extension: '.txt' }),
      file({ id: 'image', name: 'alpha.png', preview_kind: 'image', extension: '.png' }),
      file({ id: 'text-a', name: 'alpha.txt', preview_kind: 'text', extension: '.txt' }),
    ])).toEqual(['image', 'text-a', 'text-b']);
  });
});

function sortIds(sortKey: FileSortKey, files: StorageFile[]) {
  return sortStorageFiles(files, sortKey).map((item) => item.id);
}

function file(overrides: Partial<StorageFile> & { id: string }): StorageFile {
  const previewKind = overrides.preview_kind || 'file';
  const name = overrides.name || `${overrides.id}.txt`;
  const base: StorageFile = {
    id: overrides.id,
    file_id: overrides.id,
    path_id: `generated:${name}`,
    role: 'generated',
    name,
    relative_path: name,
    workspace_relative_path: `storage/generated/${name}`,
    extension: overrides.extension || '.txt',
    size_bytes: overrides.size_bytes ?? 0,
    created_at: overrides.created_at ?? '2026-06-01T00:00:00Z',
    modified_at: overrides.modified_at || '2026-06-01T00:00:00Z',
    content_type: 'text/plain',
    preview_kind: previewKind as PreviewKind,
    sha256: ''
  };
  return { ...base, ...overrides };
}
