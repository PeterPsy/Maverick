import type { FileRole, PreviewKind, StorageFile, StorageViewFilter } from '../types';
import { fileFolderSelection, normalizeFolderPath } from './storageFolderLayer';

export type FolderNavigationPlan = {
  filter: Pick<StorageViewFilter, 'query' | 'role'>;
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

export const NAVIGATION_TARGET_NOT_FOUND_MESSAGE = 'Storage file not found.';

export function folderOpenRefreshPlan({
  activeRole,
  folderPath,
  folderRole,
  query,
  viewMode,
}: {
  activeRole: FileRole | 'all';
  folderPath: string;
  folderRole: FileRole;
  query: string;
  viewMode: StorageViewFilter['mode'];
}): FolderNavigationPlan {
  const normalizedFolderPath = normalizeFolderPath(folderPath);
  return {
    filter: { query: '', role: folderRole },
    folderPath: normalizedFolderPath,
    refreshOptions: { folderPath: normalizedFolderPath },
    shouldWriteViewFilter: activeRole !== folderRole || viewMode === 'custom' || Boolean(query.trim()),
    viewFilterOptions: { folderPath: normalizedFolderPath, preserveCustom: false },
  };
}

export function breadcrumbRefreshPlan({
  activeRole,
  folderPath,
  query,
  viewMode,
}: {
  activeRole: FileRole;
  folderPath: string;
  query: string;
  viewMode: StorageViewFilter['mode'];
}): FolderNavigationPlan {
  const normalizedFolderPath = normalizeFolderPath(folderPath);
  return {
    filter: { query: '', role: activeRole },
    folderPath: normalizedFolderPath,
    refreshOptions: { folderPath: normalizedFolderPath },
    shouldWriteViewFilter: viewMode === 'custom' || Boolean(query.trim()),
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

export function missingNavigationTargetPlan() {
  return {
    clearPending: true,
    error: NAVIGATION_TARGET_NOT_FOUND_MESSAGE,
  };
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
