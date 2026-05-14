import { describe, expect, it } from 'vitest';
import { applyStorageCatalogDelta, applyStorageFoldersDelta } from './storageCatalogDelta';
import type { StorageFile, StorageFolder } from '../types';

describe('Storage catalog deltas', () => {
  it('upserts a moved file and removes its previous path', () => {
    const moved = file({ id: 'file_a', relative_path: 'Archive/report.md' });
    const snapshot = applyStorageCatalogDelta({
      files: [file({ id: 'file_a', relative_path: 'report.md' }), file({ id: 'file_b', relative_path: 'notes.md' })],
      folders: [],
    }, {
      type: 'upsert_file',
      file: moved,
      previous: { role: 'generated', relative_path: 'report.md', id: 'file_a', file_id: 'file_a' },
    });

    expect(snapshot.files.map((item) => item.workspace_relative_path)).toEqual([
      'storage/generated/notes.md',
      'storage/generated/Archive/report.md',
    ]);
  });

  it('removes a deleted folder subtree from loaded files and folders', () => {
    const snapshot = applyStorageCatalogDelta({
      files: [
        file({ relative_path: 'Reports/summary.md' }),
        file({ relative_path: 'Reports/Q1/data.csv' }),
        file({ relative_path: 'Other/notes.md' }),
      ],
      folders: [
        folder({ relative_path: 'Reports' }),
        folder({ relative_path: 'Reports/Q1' }),
        folder({ relative_path: 'Other' }),
      ],
    }, {
      type: 'delete_folder',
      folder: folder({ relative_path: 'Reports' }),
    });

    expect(snapshot.files.map((item) => item.relative_path)).toEqual(['Other/notes.md']);
    expect(snapshot.folders.map((item) => item.relative_path)).toEqual(['Other']);
  });

  it('rewrites loaded descendants when a folder moves', () => {
    const snapshot = applyStorageCatalogDelta({
      files: [
        file({ id: 'file_a', relative_path: 'Reports/summary.md' }),
        file({ id: 'file_b', relative_path: 'Reports/Q1/data.csv' }),
        file({ id: 'file_c', relative_path: 'Other/notes.md' }),
      ],
      folders: [
        folder({ relative_path: 'Reports' }),
        folder({ relative_path: 'Reports/Q1' }),
        folder({ relative_path: 'Other' }),
      ],
    }, {
      type: 'move_folder',
      previous: folder({ relative_path: 'Reports' }),
      folder: folder({ relative_path: 'Archive/Reports' }),
    });

    expect(snapshot.files.map((item) => item.workspace_relative_path)).toEqual([
      'storage/generated/Archive/Reports/summary.md',
      'storage/generated/Archive/Reports/Q1/data.csv',
      'storage/generated/Other/notes.md',
    ]);
    expect(snapshot.folders.map((item) => item.workspace_relative_path)).toEqual([
      'storage/generated/Archive/Reports',
      'storage/generated/Archive/Reports/Q1',
      'storage/generated/Other',
    ]);
  });

  it('patches sidebar folder lists without requiring loaded files', () => {
    const folders = applyStorageFoldersDelta([
      folder({ relative_path: 'Reports' }),
      folder({ relative_path: 'Reports/Q1' }),
    ], {
      type: 'move_folder',
      previous: folder({ relative_path: 'Reports' }),
      folder: folder({ relative_path: 'Archive/Reports' }),
    });

    expect(folders.map((item) => item.relative_path)).toEqual(['Archive/Reports', 'Archive/Reports/Q1']);
  });
});

function file(overrides: Partial<StorageFile> = {}): StorageFile {
  const role = overrides.role || 'generated';
  const relativePath = overrides.relative_path || 'report.md';
  const id = overrides.id || `file_${relativePath.replace(/[^a-z0-9]+/gi, '_')}`;
  return {
    id,
    file_id: overrides.file_id || id,
    path_id: overrides.path_id || `${role}:${relativePath}`,
    role,
    name: overrides.name || relativePath.split('/').pop() || 'file',
    relative_path: relativePath,
    workspace_relative_path: overrides.workspace_relative_path || `storage/${role}/${relativePath}`,
    extension: overrides.extension || '.md',
    size_bytes: overrides.size_bytes || 10,
    modified_at: overrides.modified_at || '2026-05-14T00:00:00+00:00',
    content_type: overrides.content_type || 'text/markdown',
    preview_kind: overrides.preview_kind || 'markdown',
    sha256: overrides.sha256 || '',
  };
}

function folder(overrides: Partial<StorageFolder> = {}): StorageFolder {
  const role = overrides.role || 'generated';
  const relativePath = overrides.relative_path || 'Reports';
  return {
    id: overrides.id || `${role}:${relativePath}/`,
    role,
    name: overrides.name || relativePath.split('/').pop() || 'Generated',
    relative_path: relativePath,
    workspace_relative_path: overrides.workspace_relative_path || `storage/${role}${relativePath ? `/${relativePath}` : ''}`,
    modified_at: overrides.modified_at || '2026-05-14T00:00:00+00:00',
  };
}
