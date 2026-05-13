import { describe, expect, it } from 'vitest';
import type { StorageFile, StorageFolder } from '../types';
import { storageCustomScopedFiles, storageViewVisibleFiles, storageViewVisibleFolders } from './storageSearch';

function file(role: StorageFile['role'], relativePath: string, previewKind: StorageFile['preview_kind'] = 'text'): StorageFile {
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
    size_bytes: 10,
    modified_at: '2026-05-12T00:00:00+00:00',
    content_type: previewKind === 'pdf' ? 'application/pdf' : 'text/plain',
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

describe('Storage search visibility', () => {
  it('keeps the unsearched browser scoped to the selected folder layer', () => {
    const files = [
      file('generated', 'reports/summary.md', 'markdown'),
      file('generated', 'reports/q1/nested.md', 'markdown'),
      file('uploaded', 'reports/receipt.txt'),
    ];

    expect(storageViewVisibleFiles({
      activeRole: 'generated',
      currentFolderPath: 'reports',
      files,
      kind: 'all',
      query: '',
      viewMode: 'search',
    }).map((item) => item.relative_path)).toEqual(['reports/summary.md']);
  });

  it('searches matching files across all Storage roles and folders at once', () => {
    const files = [
      file('generated', 'reports/q1/budget.md', 'markdown'),
      file('generated', 'archive/budget.md', 'markdown'),
      file('uploaded', 'receipts/budget.pdf', 'pdf'),
      file('generated', 'reports/summary.md', 'markdown'),
    ];

    expect(storageViewVisibleFiles({
      activeRole: 'generated',
      currentFolderPath: 'reports',
      files,
      kind: 'all',
      query: 'budget',
      viewMode: 'search',
    }).map((item) => item.workspace_relative_path)).toEqual([
      'storage/generated/reports/q1/budget.md',
      'storage/generated/archive/budget.md',
      'storage/uploaded/receipts/budget.pdf',
    ]);
  });

  it('still applies file kind filters during global search', () => {
    const files = [
      file('generated', 'reports/q1/budget.md', 'markdown'),
      file('uploaded', 'receipts/budget.pdf', 'pdf'),
    ];

    expect(storageViewVisibleFiles({
      activeRole: 'generated',
      currentFolderPath: 'reports',
      files,
      kind: 'markdown',
      query: 'budget',
      viewMode: 'search',
    }).map((item) => item.workspace_relative_path)).toEqual([
      'storage/generated/reports/q1/budget.md',
    ]);
  });

  it('keeps legacy path ids visible in custom views', () => {
    const files = [
      file('generated', 'reports/summary.md', 'markdown'),
      file('uploaded', 'receipts/invoice.txt'),
    ];

    expect(storageCustomScopedFiles({
      fileIds: ['generated:reports/summary.md'],
      files,
      viewMode: 'custom',
      workspaceRelativePaths: [],
    }).map((item) => item.workspace_relative_path)).toEqual(['storage/generated/reports/summary.md']);
  });

  it('keeps stable file ids visible in custom views', () => {
    const selected = file('generated', 'reports/summary.md', 'markdown');
    selected.id = 'file_summary';
    selected.file_id = 'file_summary';
    const files = [
      selected,
      file('uploaded', 'receipts/invoice.txt'),
    ];

    expect(storageCustomScopedFiles({
      fileIds: ['file_summary'],
      files,
      viewMode: 'custom',
      workspaceRelativePaths: [],
    }).map((item) => item.workspace_relative_path)).toEqual(['storage/generated/reports/summary.md']);
  });

  it('searches folders globally without exposing uploaded implementation buckets', () => {
    const folders = [
      folder('generated', ''),
      folder('uploaded', ''),
      folder('generated', 'reports/archive'),
      folder('uploaded', 'receipts/archive'),
      folder('uploaded', '834cd104-3247-422b-8669-bf5787df25d8'),
    ];

    expect(storageViewVisibleFolders({
      activeRole: 'generated',
      browsableFolders: folders,
      currentFolderPath: 'reports',
      folders,
      query: 'archive',
      viewMode: 'search',
    }).map((item) => item.workspace_relative_path)).toEqual([
      'storage/generated/reports/archive',
      'storage/uploaded/receipts/archive',
    ]);
  });
});
