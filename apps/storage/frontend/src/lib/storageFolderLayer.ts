import type { FileRole, StorageFile, StorageFolder } from '../types';

export type StorageFolderSelection = {
  relativePath: string;
  role: FileRole | 'all';
};

export type StorageFolderStats = {
  fileCount: number;
  folderCount: number;
  sizeBytes: number;
};

const uploadBucketPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function normalizeFolderPath(value: string) {
  return value.split('/').filter(Boolean).join('/');
}

export function folderParentPath(relativePath: string) {
  const parts = normalizeFolderPath(relativePath).split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

export function isSystemUploadFolder(folder: Pick<StorageFolder, 'relative_path' | 'role'>) {
  const parts = normalizeFolderPath(folder.relative_path).split('/').filter(Boolean);
  return folder.role === 'uploaded' && parts.length === 1 && uploadBucketPattern.test(parts[0]);
}

export function visibleFileParentPath(file: Pick<StorageFile, 'relative_path' | 'role'>) {
  const parts = normalizeFolderPath(file.relative_path).split('/').filter(Boolean);
  if (file.role === 'uploaded' && parts.length === 2 && uploadBucketPattern.test(parts[0])) {
    return '';
  }
  return folderParentPath(file.relative_path);
}

export function fileFolderSelection(file: Pick<StorageFile, 'relative_path' | 'role'>): StorageFolderSelection {
  return {
    relativePath: visibleFileParentPath(file),
    role: file.role,
  };
}

export function isDirectFolderChild(folder: StorageFolder, selection: StorageFolderSelection) {
  if (selection.role === 'all' || folder.role !== selection.role || isSystemUploadFolder(folder)) {
    return false;
  }
  const folderPath = normalizeFolderPath(folder.relative_path);
  if (!folderPath) {
    return false;
  }
  return folderParentPath(folderPath) === normalizeFolderPath(selection.relativePath);
}

export function isDirectFileChild(file: StorageFile, selection: StorageFolderSelection) {
  if (selection.role === 'all' || file.role !== selection.role) {
    return false;
  }
  return visibleFileParentPath(file) === normalizeFolderPath(selection.relativePath);
}

function selectionContainsPath(selection: StorageFolderSelection, relativePath: string) {
  if (selection.role === 'all') {
    return true;
  }
  const folderPath = normalizeFolderPath(selection.relativePath);
  const childPath = normalizeFolderPath(relativePath);
  return !folderPath || childPath === folderPath || childPath.startsWith(`${folderPath}/`);
}

export function folderStatsForSelection(selection: StorageFolderSelection, files: StorageFile[], folders: StorageFolder[]): StorageFolderStats {
  const selectedPath = normalizeFolderPath(selection.relativePath);
  const childFiles = files.filter((file) => {
    if (selection.role !== 'all' && file.role !== selection.role) {
      return false;
    }
    return selectionContainsPath(selection, fileFolderSelection(file).relativePath);
  });
  const childFolders = folders.filter((folder) => {
    if ((selection.role !== 'all' && folder.role !== selection.role) || isSystemUploadFolder(folder)) {
      return false;
    }
    if (selection.role === 'all') {
      return true;
    }
    const folderPath = normalizeFolderPath(folder.relative_path);
    return Boolean(folderPath) && folderPath !== selectedPath && selectionContainsPath(selection, folderPath);
  });
  return {
    fileCount: childFiles.length,
    folderCount: childFolders.length,
    sizeBytes: childFiles.reduce((total, file) => total + file.size_bytes, 0),
  };
}

export function directLayerFolders(folders: StorageFolder[], selection: StorageFolderSelection) {
  return folders.filter((folder) => isDirectFolderChild(folder, selection));
}

export function directLayerFiles(files: StorageFile[], selection: StorageFolderSelection) {
  return files.filter((file) => isDirectFileChild(file, selection));
}
