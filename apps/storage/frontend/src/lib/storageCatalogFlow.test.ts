import { describe, expect, it } from 'vitest';
import type { StorageFile } from '../types';
import {
  breadcrumbRefreshPlan,
  catalogLoadedCountAfterPage,
  catalogLoadedCountAfterRefresh,
  deleteFileWithCatalogRefresh,
  folderOpenRefreshPlan,
  resolvedFileNavigationPlan,
} from './storageCatalogFlow';

function file(role: StorageFile['role'], relativePath: string): StorageFile {
  const name = relativePath.split('/').filter(Boolean).at(-1) || 'file.txt';
  return {
    id: `file_${name}`,
    file_id: `file_${name}`,
    path_id: `${role}:${relativePath}`,
    role,
    name,
    relative_path: relativePath,
    workspace_relative_path: `storage/${role}/${relativePath}`,
    extension: '.txt',
    size_bytes: 10,
    modified_at: '2026-05-12T00:00:00+00:00',
    content_type: 'text/plain',
    preview_kind: 'text',
    sha256: '',
  };
}

describe('storage catalog flow planning', () => {
  it('refreshes the target folder directly when opening inside the same role', () => {
    const plan = folderOpenRefreshPlan({
      activeRole: 'generated',
      folderPath: '/Reports/Q1/',
      folderRole: 'generated',
      viewMode: 'search',
    });

    expect(plan).toMatchObject({
      filter: { role: 'generated' },
      folderPath: 'Reports/Q1',
      refreshOptions: { folderPath: 'Reports/Q1' },
      shouldWriteViewFilter: false,
    });
  });

  it('writes search view-state when folder navigation leaves custom mode', () => {
    const plan = folderOpenRefreshPlan({
      activeRole: 'generated',
      folderPath: 'Reports',
      folderRole: 'generated',
      viewMode: 'custom',
    });

    expect(plan.shouldWriteViewFilter).toBe(true);
    expect(plan.viewFilterOptions).toEqual({ folderPath: 'Reports', preserveCustom: false });
  });

  it('uses explicit refresh plans for breadcrumb jumps', () => {
    const searchPlan = breadcrumbRefreshPlan({ activeRole: 'uploaded', folderPath: '', viewMode: 'search' });
    const customPlan = breadcrumbRefreshPlan({ activeRole: 'uploaded', folderPath: 'Client Docs', viewMode: 'custom' });

    expect(searchPlan).toMatchObject({
      filter: { role: 'uploaded' },
      folderPath: '',
      refreshOptions: { folderPath: '' },
      shouldWriteViewFilter: false,
    });
    expect(customPlan).toMatchObject({
      folderPath: 'Client Docs',
      shouldWriteViewFilter: true,
      viewFilterOptions: { folderPath: 'Client Docs', preserveCustom: false },
    });
  });

  it('resets direct file navigation to the resolved file folder catalog', () => {
    const plan = resolvedFileNavigationPlan(file('generated', 'Reports/Q1/deep.txt'));

    expect(plan).toEqual({
      filter: { query: '', role: 'generated', kind: 'all' },
      folderPath: 'Reports/Q1',
      refreshOptions: { fileIds: [], folderPath: 'Reports/Q1', viewMode: 'search', workspacePaths: [] },
    });
  });

  it('keeps uploaded implementation bucket files at the visible uploaded root', () => {
    const plan = resolvedFileNavigationPlan(file('uploaded', '834cd104-3247-422b-8669-bf5787df25d8/invoice.txt'));

    expect(plan.folderPath).toBe('');
    expect(plan.refreshOptions.folderPath).toBe('');
  });

  it('tracks catalog offsets from catalog pages instead of merged local files', () => {
    expect(catalogLoadedCountAfterRefresh(500)).toBe(500);
    expect(catalogLoadedCountAfterPage(500, 25)).toBe(525);
    expect(catalogLoadedCountAfterPage(500, 0)).toBe(500);
  });

  it('refreshes the catalog after deleting a file', async () => {
    const deleted = file('generated', 'Reports/Q1/deep.txt');
    const calls: string[] = [];

    await deleteFileWithCatalogRefresh(deleted, {
      clearSelectedFile: (fileId) => calls.push(`clear:${fileId}`),
      deleteFile: async (item) => {
        calls.push(`delete:${item.id}`);
      },
      refresh: async () => {
        calls.push('refresh');
      },
    });

    expect(calls).toEqual([`delete:${deleted.id}`, `clear:${deleted.id}`, 'refresh']);
  });
});
