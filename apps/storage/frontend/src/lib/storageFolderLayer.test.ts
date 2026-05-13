import { describe, expect, it } from 'vitest';
import type { StorageFile, StorageFolder } from '../types';
import {
  directLayerFiles,
  directLayerFolders,
  fileFolderSelection,
  folderStatsForSelection,
  folderParentPath,
  isDirectFileChild,
  normalizeFolderPath,
  visibleFileParentPath,
} from './storageFolderLayer';

function file(role: StorageFile['role'], relativePath: string, previewKind: StorageFile['preview_kind'] = 'text', sizeBytes = 10): StorageFile {
  const name = relativePath.split('/').filter(Boolean).at(-1) || 'file.txt';
  return {
    id: `${role}:${relativePath}`,
    file_id: `${role}:${relativePath}`,
    path_id: `${role}:${relativePath}`,
    role,
    name,
    relative_path: relativePath,
    workspace_relative_path: `storage/${role}/${relativePath}`,
    extension: '.txt',
    size_bytes: sizeBytes,
    modified_at: '2026-05-12T00:00:00+00:00',
    content_type: 'text/plain',
    preview_kind: previewKind,
    sha256: '',
  };
}

function folder(role: StorageFolder['role'], relativePath: string): StorageFolder {
  const name = relativePath.split('/').filter(Boolean).at(-1) || role;
  return {
    id: `${role}:${relativePath}/`,
    role,
    name,
    relative_path: relativePath,
    workspace_relative_path: relativePath ? `storage/${role}/${relativePath}` : `storage/${role}`,
    modified_at: '2026-05-12T00:00:00+00:00',
  };
}

describe('Storage folder layer helpers', () => {
  it('normalizes folder paths and derives direct parents', () => {
    expect(normalizeFolderPath('/reports/q1/')).toBe('reports/q1');
    expect(folderParentPath('reports/q1')).toBe('reports');
    expect(folderParentPath('reports')).toBe('');
  });

  it('returns only direct folder and file children for a selected folder', () => {
    const folders = [
      folder('generated', 'reports/q1'),
      folder('generated', 'reports/q2'),
      folder('generated', 'reports/q1/archive'),
      folder('uploaded', 'reports/q1'),
    ];
    const files = [
      file('generated', 'reports/summary.md', 'markdown'),
      file('generated', 'reports/q1/nested.md', 'markdown'),
      file('generated', 'reports/q1/archive/deep.md', 'markdown'),
      file('uploaded', 'reports/receipt.txt'),
    ];

    const selection = { role: 'generated' as const, relativePath: 'reports' };

    expect(directLayerFolders(folders, selection).map((item) => item.relative_path)).toEqual(['reports/q1', 'reports/q2']);
    expect(directLayerFiles(files, selection).map((item) => item.relative_path)).toEqual(['reports/summary.md']);
  });

  it('keeps folder selection role-aware when roles share a relative path', () => {
    expect(isDirectFileChild(file('uploaded', 'reports/receipt.txt'), { role: 'generated', relativePath: 'reports' })).toBe(false);
    expect(isDirectFileChild(file('generated', 'reports/summary.md'), { role: 'generated', relativePath: 'reports' })).toBe(true);
  });

  it('surfaces files from uploaded UUID buckets at the visible uploaded root', () => {
    const bucketed = file('uploaded', '834cd104-3247-422b-8669-bf5787df25d8/image.png', 'image');

    expect(visibleFileParentPath(bucketed)).toBe('');
    expect(fileFolderSelection(bucketed)).toEqual({ role: 'uploaded', relativePath: '' });
    expect(isDirectFileChild(bucketed, { role: 'uploaded', relativePath: '' })).toBe(true);
  });

  it('aggregates recursive folder stats for the current folder selection', () => {
    const folders = [
      folder('generated', 'reports'),
      folder('generated', 'reports/q1'),
      folder('generated', 'reports/q1/archive'),
      folder('uploaded', 'reports'),
    ];
    const files = [
      file('generated', 'reports/summary.md', 'markdown', 1024),
      file('generated', 'reports/q1/nested.md', 'markdown', 2048),
      file('generated', 'reports/q1/archive/deep.md', 'markdown', 4096),
      file('uploaded', 'reports/receipt.txt', 'text', 8192),
    ];

    expect(folderStatsForSelection({ role: 'generated', relativePath: 'reports' }, files, folders)).toEqual({
      fileCount: 3,
      folderCount: 2,
      sizeBytes: 7168,
    });
  });

  it('includes uploaded UUID bucket files in the visible uploaded root size', () => {
    const bucketed = file('uploaded', '834cd104-3247-422b-8669-bf5787df25d8/image.png', 'image', 2048);
    const direct = file('uploaded', 'manual.pdf', 'pdf', 4096);

    expect(folderStatsForSelection({ role: 'uploaded', relativePath: '' }, [bucketed, direct], [])).toEqual({
      fileCount: 2,
      folderCount: 0,
      sizeBytes: 6144,
    });
  });
});
