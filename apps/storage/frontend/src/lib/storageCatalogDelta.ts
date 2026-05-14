import type { StorageFile, StorageFolder } from '../types';

type FileReference = Pick<StorageFile, 'role' | 'relative_path'> & Partial<Pick<StorageFile, 'id' | 'file_id' | 'workspace_relative_path'>>;
type FolderReference = Pick<StorageFolder, 'role' | 'relative_path'> & Partial<Pick<StorageFolder, 'id' | 'workspace_relative_path'>>;

export type StorageCatalogDelta =
  | { type: 'upsert_file'; file: StorageFile; previous?: FileReference | null }
  | { type: 'delete_file'; file: FileReference }
  | { type: 'upsert_folder'; folder: StorageFolder; previous?: FolderReference | null }
  | { type: 'delete_folder'; folder: FolderReference }
  | { type: 'move_folder'; folder: StorageFolder; previous: FolderReference };

export type StorageCatalogSnapshot = {
  files: StorageFile[];
  folders: StorageFolder[];
};

export function applyStorageCatalogDelta(snapshot: StorageCatalogSnapshot, delta: StorageCatalogDelta): StorageCatalogSnapshot {
  switch (delta.type) {
    case 'upsert_file':
      return {
        files: upsertFile(snapshot.files, delta.file, delta.previous),
        folders: snapshot.folders,
      };
    case 'delete_file':
      return {
        files: snapshot.files.filter((file) => !sameFileReference(file, delta.file)),
        folders: snapshot.folders,
      };
    case 'upsert_folder':
      return {
        files: snapshot.files,
        folders: upsertFolder(snapshot.folders, delta.folder, delta.previous),
      };
    case 'delete_folder':
      return {
        files: removeFilesInFolder(snapshot.files, delta.folder),
        folders: removeFolderTree(snapshot.folders, delta.folder),
      };
    case 'move_folder':
      return moveFolderTree(snapshot, delta.previous, delta.folder);
  }
}

export function applyStorageFilesDelta(files: StorageFile[], delta: StorageCatalogDelta): StorageFile[] {
  return applyStorageCatalogDelta({ files, folders: [] }, delta).files;
}

export function applyStorageFoldersDelta(folders: StorageFolder[], delta: StorageCatalogDelta): StorageFolder[] {
  return applyStorageCatalogDelta({ files: [], folders }, delta).folders;
}

function upsertFile(files: StorageFile[], file: StorageFile, previous?: FileReference | null) {
  return [
    ...files.filter((item) => !sameFileReference(item, file) && !(previous && sameFileReference(item, previous))),
    file,
  ];
}

function upsertFolder(folders: StorageFolder[], folder: StorageFolder, previous?: FolderReference | null) {
  return dedupeFolders([
    ...folders.filter((item) => !sameFolderReference(item, folder) && !(previous && sameFolderReference(item, previous))),
    folder,
  ]);
}

function removeFilesInFolder(files: StorageFile[], folder: FolderReference) {
  const folderPath = normalizePath(folder.relative_path);
  if (!folderPath) {
    return files;
  }
  return files.filter((file) => file.role !== folder.role || !pathIsSelfOrChild(file.relative_path, folderPath));
}

function removeFolderTree(folders: StorageFolder[], folder: FolderReference) {
  const folderPath = normalizePath(folder.relative_path);
  if (!folderPath) {
    return folders;
  }
  return folders.filter((item) => item.role !== folder.role || !pathIsSelfOrChild(item.relative_path, folderPath));
}

function moveFolderTree(snapshot: StorageCatalogSnapshot, previous: FolderReference, folder: StorageFolder): StorageCatalogSnapshot {
  const oldPath = normalizePath(previous.relative_path);
  const newPath = normalizePath(folder.relative_path);
  if (!oldPath) {
    return snapshot;
  }
  const files = snapshot.files.map((file) => {
    if (file.role !== previous.role || !pathIsSelfOrChild(file.relative_path, oldPath)) {
      return file;
    }
    const relativePath = pathAfterMove(file.relative_path, oldPath, newPath);
    return {
      ...file,
      path_id: `${file.role}:${relativePath}`,
      relative_path: relativePath,
      workspace_relative_path: workspacePath(file.role, relativePath),
    };
  });
  const folders = dedupeFolders([
    ...snapshot.folders
      .filter((item) => !sameFolderReference(item, folder))
      .map((item) => {
        if (item.role !== previous.role || !pathIsSelfOrChild(item.relative_path, oldPath)) {
          return item;
        }
        const relativePath = pathAfterMove(item.relative_path, oldPath, newPath);
        return {
          ...item,
          id: `${item.role}:${relativePath}/`,
          relative_path: relativePath,
          workspace_relative_path: workspacePath(item.role, relativePath),
        };
      }),
    folder,
  ]);
  return { files, folders };
}

function sameFileReference(file: StorageFile, reference: FileReference) {
  return Boolean(
    (reference.id && file.id === reference.id)
    || (reference.file_id && file.file_id === reference.file_id)
    || (reference.workspace_relative_path && file.workspace_relative_path === reference.workspace_relative_path)
    || (file.role === reference.role && normalizePath(file.relative_path) === normalizePath(reference.relative_path))
  );
}

function sameFolderReference(folder: StorageFolder, reference: FolderReference) {
  return Boolean(
    (reference.id && folder.id === reference.id)
    || (reference.workspace_relative_path && folder.workspace_relative_path === reference.workspace_relative_path)
    || (folder.role === reference.role && normalizePath(folder.relative_path) === normalizePath(reference.relative_path))
  );
}

function pathIsSelfOrChild(path: string, parentPath: string) {
  const normalizedPath = normalizePath(path);
  const normalizedParent = normalizePath(parentPath);
  return normalizedPath === normalizedParent || normalizedPath.startsWith(`${normalizedParent}/`);
}

function pathAfterMove(path: string, oldPath: string, newPath: string) {
  const normalizedPath = normalizePath(path);
  const normalizedOldPath = normalizePath(oldPath);
  const normalizedNewPath = normalizePath(newPath);
  if (normalizedPath === normalizedOldPath) {
    return normalizedNewPath;
  }
  const suffix = normalizedPath.slice(normalizedOldPath.length + 1);
  return normalizedNewPath ? `${normalizedNewPath}/${suffix}` : suffix;
}

function workspacePath(role: StorageFile['role'], relativePath: string) {
  return `storage/${role}${relativePath ? `/${relativePath}` : ''}`;
}

function normalizePath(path: string) {
  return String(path || '').split('/').filter(Boolean).join('/');
}

function dedupeFolders(folders: StorageFolder[]) {
  const byId = new Map<string, StorageFolder>();
  folders.forEach((folder) => byId.set(folder.id, folder));
  return Array.from(byId.values());
}
