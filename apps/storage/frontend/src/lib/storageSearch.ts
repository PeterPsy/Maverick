import type { FileRole, PreviewKind, StorageFile, StorageFolder, StorageViewFilter } from '../types';
import { directLayerFiles, directLayerFolders, isSystemUploadFolder } from './storageFolderLayer';

type VisibleFoldersOptions = {
  activeRole: FileRole | 'all';
  browsableFolders: StorageFolder[];
  currentFolderPath: string;
  folders: StorageFolder[];
  query: string;
  viewMode: StorageViewFilter['mode'];
};

type VisibleFilesOptions = {
  activeRole: FileRole | 'all';
  currentFolderPath: string;
  files: StorageFile[];
  kind: PreviewKind | 'all' | string;
  query: string;
  viewMode: StorageViewFilter['mode'];
};

type CustomScopedFilesOptions = {
  fileIds: string[];
  files: StorageFile[];
  viewMode: StorageViewFilter['mode'];
  workspaceRelativePaths: string[];
};

function searchNeedle(query: string) {
  return query.trim().toLowerCase();
}

function folderSearchText(folder: StorageFolder) {
  return `${folder.name} ${folder.workspace_relative_path}`.toLowerCase();
}

function fileSearchText(file: StorageFile) {
  return `${file.name} ${file.workspace_relative_path} ${file.content_type}`.toLowerCase();
}

export function storageViewVisibleFolders({
  activeRole,
  browsableFolders,
  currentFolderPath,
  folders,
  query,
  viewMode,
}: VisibleFoldersOptions) {
  if (viewMode === 'custom') return [];
  const needle = searchNeedle(query);
  const scopedFolders = needle
    ? browsableFolders.filter((folder) => !isSystemUploadFolder(folder))
    : activeRole === 'all'
      ? browsableFolders.filter((folder) => !folder.relative_path)
      : directLayerFolders(folders, { role: activeRole, relativePath: currentFolderPath });
  return scopedFolders.filter((folder) => !needle || folderSearchText(folder).includes(needle));
}

export function storageViewVisibleFiles({
  activeRole,
  currentFolderPath,
  files,
  kind,
  query,
  viewMode,
}: VisibleFilesOptions) {
  const needle = searchNeedle(query);
  const isGlobalSearch = viewMode !== 'custom' && Boolean(needle);
  const scopedFiles = viewMode === 'custom' || isGlobalSearch
    ? files
    : directLayerFiles(files, { role: activeRole, relativePath: currentFolderPath });
  return scopedFiles.filter((file) => {
    const roleMatch = isGlobalSearch || activeRole === 'all' || file.role === activeRole;
    const kindMatch = kind === 'all' || file.preview_kind === kind;
    const textMatch = !needle || fileSearchText(file).includes(needle);
    return roleMatch && kindMatch && textMatch;
  });
}

export function storageCustomScopedFiles({
  fileIds,
  files,
  viewMode,
  workspaceRelativePaths,
}: CustomScopedFilesOptions) {
  if (viewMode !== 'custom') return files;
  const customIds = new Set(fileIds);
  const customPaths = new Set(workspaceRelativePaths);
  return files.filter((file) => customIds.has(file.id) || customIds.has(file.file_id) || customIds.has(file.path_id) || customPaths.has(file.workspace_relative_path));
}
