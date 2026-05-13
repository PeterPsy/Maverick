import type { FileRole, PreviewKind, StorageFile, StorageViewFilter } from '../types';
import { fileFolderSelection, normalizeFolderPath } from './storageFolderLayer';

export type FolderNavigationPlan = {
  filter: Pick<StorageViewFilter, 'role'>;
  folderPath: string;
  refreshOptions: { folderPath: string };
  shouldWriteViewFilter: boolean;
  viewFilterOptions: { folderPath: string; preserveCustom: false };
};

export type ResolvedFileNavigationPlan = {
  filter: { query: string; role: FileRole; kind: PreviewKind | 'all' };
  folderPath: string;
  refreshOptions: { fileIds: []; folderPath: string; viewMode: 'search'; workspacePaths: [] };
};

export function folderOpenRefreshPlan({
  activeRole,
  folderPath,
  folderRole,
  viewMode,
}: {
  activeRole: FileRole | 'all';
  folderPath: string;
  folderRole: FileRole;
  viewMode: StorageViewFilter['mode'];
}): FolderNavigationPlan {
  const normalizedFolderPath = normalizeFolderPath(folderPath);
  return {
    filter: { role: folderRole },
    folderPath: normalizedFolderPath,
    refreshOptions: { folderPath: normalizedFolderPath },
    shouldWriteViewFilter: activeRole !== folderRole || viewMode === 'custom',
    viewFilterOptions: { folderPath: normalizedFolderPath, preserveCustom: false },
  };
}

export function breadcrumbRefreshPlan({
  activeRole,
  folderPath,
  viewMode,
}: {
  activeRole: FileRole;
  folderPath: string;
  viewMode: StorageViewFilter['mode'];
}): FolderNavigationPlan {
  const normalizedFolderPath = normalizeFolderPath(folderPath);
  return {
    filter: { role: activeRole },
    folderPath: normalizedFolderPath,
    refreshOptions: { folderPath: normalizedFolderPath },
    shouldWriteViewFilter: viewMode === 'custom',
    viewFilterOptions: { folderPath: normalizedFolderPath, preserveCustom: false },
  };
}

export function resolvedFileNavigationPlan(file: StorageFile): ResolvedFileNavigationPlan {
  const fileFolder = fileFolderSelection(file);
  return {
    filter: { query: '', role: fileFolder.role as FileRole, kind: 'all' },
    folderPath: fileFolder.relativePath,
    refreshOptions: { fileIds: [], folderPath: fileFolder.relativePath, viewMode: 'search', workspacePaths: [] },
  };
}

export function catalogLoadedCountAfterRefresh(pageLength: number) {
  return Math.max(0, pageLength);
}

export function catalogLoadedCountAfterPage(currentLoadedCount: number, pageLength: number) {
  return Math.max(0, currentLoadedCount) + Math.max(0, pageLength);
}

export async function deleteFileWithCatalogRefresh(
  file: StorageFile,
  actions: {
    clearSelectedFile: (fileId: string) => void;
    deleteFile: (file: StorageFile) => Promise<unknown>;
    refresh: () => Promise<unknown>;
  }
) {
  await actions.deleteFile(file);
  actions.clearSelectedFile(file.id);
  await actions.refresh();
}
