import type { FileRole, PreviewKind, StorageFile, StorageFolder } from '../types';

export const STORAGE_FILE_DRAG_DATA_TYPE = 'application/x-maverick-storage-file';
export const STORAGE_FOLDER_DRAG_DATA_TYPE = 'application/x-maverick-storage-folder';
export const STORAGE_SELECTION_DRAG_DATA_TYPE = 'application/x-maverick-storage-selection';

const STORAGE_FILE_DRAG_ROLE_TYPE_PREFIX = 'application/x-maverick-storage-file-role-';
const STORAGE_FOLDER_DRAG_ROLE_TYPE_PREFIX = 'application/x-maverick-storage-folder-role-';
const STORAGE_SELECTION_DRAG_ROLE_TYPE_PREFIX = 'application/x-maverick-storage-selection-role-';
const STORAGE_FILE_ROLES: FileRole[] = ['uploaded', 'generated'];

export type StorageFileDragPayload = {
  file_id: string;
  name: string;
  owner_app_id: string;
  preview_kind?: PreviewKind;
  relative_path: string;
  role: FileRole;
  workspace_relative_path: string;
};

export type StorageFolderDragPayload = {
  folder_id: string;
  name: string;
  owner_app_id: string;
  relative_path: string;
  role: FileRole;
  workspace_relative_path: string;
};

export type StorageSelectionDragPayload = {
  files: StorageFileDragPayload[];
  folders: StorageFolderDragPayload[];
  owner_app_id: string;
};

export type StorageFileDropStatus = 'none' | 'ready' | 'blocked';
export type StorageMoveDropStatus = StorageFileDropStatus;

type StorageDragDataTransfer = Pick<DataTransfer, 'getData' | 'setData' | 'types'> & {
  effectAllowed?: DataTransfer['effectAllowed'];
};

type StorageDropDataTransfer = Pick<DataTransfer, 'types'>;

export function storageDragPayloadFromFile(file: StorageFile, ownerAppId: string): StorageFileDragPayload {
  return {
    file_id: file.file_id || file.id,
    name: file.name,
    owner_app_id: ownerAppId,
    preview_kind: file.preview_kind,
    relative_path: file.relative_path,
    role: file.role as FileRole,
    workspace_relative_path: file.workspace_relative_path,
  };
}

export function storageDragPayloadFromFolder(folder: StorageFolder, ownerAppId: string): StorageFolderDragPayload {
  return {
    folder_id: folder.id,
    name: folder.name,
    owner_app_id: ownerAppId,
    relative_path: folder.relative_path,
    role: folder.role as FileRole,
    workspace_relative_path: folder.workspace_relative_path,
  };
}

export function storageDragPayloadFromSelection(
  selection: { files: StorageFile[]; folders: StorageFolder[] },
  ownerAppId: string
): StorageSelectionDragPayload {
  return {
    files: uniqueStorageFiles(selection.files).map((file) => storageDragPayloadFromFile(file, ownerAppId)),
    folders: uniqueStorageFolders(selection.folders).map((folder) => storageDragPayloadFromFolder(folder, ownerAppId)),
    owner_app_id: ownerAppId,
  };
}

export function writeStorageFileDragData(dataTransfer: StorageDragDataTransfer, payload: StorageFileDragPayload) {
  dataTransfer.setData(STORAGE_FILE_DRAG_DATA_TYPE, JSON.stringify(payload));
  dataTransfer.setData(storageFileDragRoleType(payload.role), payload.role);
  dataTransfer.effectAllowed = 'copyMove';
}

export function writeStorageFolderDragData(dataTransfer: StorageDragDataTransfer, payload: StorageFolderDragPayload) {
  dataTransfer.setData(STORAGE_FOLDER_DRAG_DATA_TYPE, JSON.stringify(payload));
  dataTransfer.setData(storageFolderDragRoleType(payload.role), payload.role);
  dataTransfer.effectAllowed = 'copyMove';
}

export function writeStorageSelectionDragData(dataTransfer: StorageDragDataTransfer, payload: StorageSelectionDragPayload) {
  if (!payload.files.length && !payload.folders.length) {
    return;
  }
  dataTransfer.setData(STORAGE_SELECTION_DRAG_DATA_TYPE, JSON.stringify(payload));
  storageSelectionRoles(payload).forEach((role) => dataTransfer.setData(storageSelectionDragRoleType(role), role));
  dataTransfer.effectAllowed = 'copyMove';
}

export function readStorageFileDragData(dataTransfer: Pick<DataTransfer, 'getData'>, expectedOwnerAppId?: string) {
  const rawPayload = dataTransfer.getData(STORAGE_FILE_DRAG_DATA_TYPE);
  if (!rawPayload) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawPayload);
  } catch {
    return null;
  }

  const payload = normalizeStorageFileDragPayload(parsed);
  if (!payload) {
    return null;
  }
  if (expectedOwnerAppId && payload.owner_app_id !== expectedOwnerAppId) {
    return null;
  }
  return payload;
}

export function readStorageFolderDragData(dataTransfer: Pick<DataTransfer, 'getData'>, expectedOwnerAppId?: string) {
  const rawPayload = dataTransfer.getData(STORAGE_FOLDER_DRAG_DATA_TYPE);
  if (!rawPayload) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawPayload);
  } catch {
    return null;
  }

  const payload = normalizeStorageFolderDragPayload(parsed);
  if (!payload) {
    return null;
  }
  if (expectedOwnerAppId && payload.owner_app_id !== expectedOwnerAppId) {
    return null;
  }
  return payload;
}

export function readStorageSelectionDragData(dataTransfer: Pick<DataTransfer, 'getData'>, expectedOwnerAppId?: string) {
  const rawPayload = dataTransfer.getData(STORAGE_SELECTION_DRAG_DATA_TYPE);
  if (!rawPayload) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawPayload);
  } catch {
    return null;
  }

  const payload = normalizeStorageSelectionDragPayload(parsed);
  if (!payload) {
    return null;
  }
  if (expectedOwnerAppId && payload.owner_app_id !== expectedOwnerAppId) {
    return null;
  }
  return payload;
}

export function storageFileDropStatus(dataTransfer: StorageDropDataTransfer, targetRole: FileRole | 'all'): StorageFileDropStatus {
  if (!hasStorageFileDragData(dataTransfer)) {
    return 'none';
  }
  if (targetRole === 'all') {
    return 'blocked';
  }
  const sourceRoles = storageFileDragRoles(dataTransfer);
  if (sourceRoles.length && sourceRoles.some((role) => role !== targetRole)) {
    return 'blocked';
  }
  return 'ready';
}

export function storageMoveDropStatus(dataTransfer: StorageDropDataTransfer, targetRole: FileRole | 'all'): StorageMoveDropStatus {
  if (!hasStorageMoveDragData(dataTransfer)) {
    return 'none';
  }
  if (targetRole === 'all') {
    return 'blocked';
  }
  const sourceRoles = storageMoveDragRoles(dataTransfer);
  if (sourceRoles.length && sourceRoles.some((role) => role !== targetRole)) {
    return 'blocked';
  }
  return 'ready';
}

export function hasStorageFileDragData(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return types.includes(STORAGE_FILE_DRAG_DATA_TYPE) || types.some((type) => type.startsWith(STORAGE_FILE_DRAG_ROLE_TYPE_PREFIX));
}

export function hasStorageFolderDragData(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return types.includes(STORAGE_FOLDER_DRAG_DATA_TYPE) || types.some((type) => type.startsWith(STORAGE_FOLDER_DRAG_ROLE_TYPE_PREFIX));
}

export function hasStorageSelectionDragData(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return types.includes(STORAGE_SELECTION_DRAG_DATA_TYPE) || types.some((type) => type.startsWith(STORAGE_SELECTION_DRAG_ROLE_TYPE_PREFIX));
}

export function hasStorageMoveDragData(dataTransfer: StorageDropDataTransfer) {
  return hasStorageFileDragData(dataTransfer) || hasStorageFolderDragData(dataTransfer) || hasStorageSelectionDragData(dataTransfer);
}

function storageFileDragRoles(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return STORAGE_FILE_ROLES.filter((role) => types.includes(storageFileDragRoleType(role)));
}

function storageFolderDragRoles(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return STORAGE_FILE_ROLES.filter((role) => types.includes(storageFolderDragRoleType(role)));
}

function storageSelectionDragRoles(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return STORAGE_FILE_ROLES.filter((role) => types.includes(storageSelectionDragRoleType(role)));
}

function storageMoveDragRoles(dataTransfer: StorageDropDataTransfer) {
  return Array.from(new Set([...storageFileDragRoles(dataTransfer), ...storageFolderDragRoles(dataTransfer), ...storageSelectionDragRoles(dataTransfer)]));
}

function storageFileDragRoleType(role: FileRole) {
  return `${STORAGE_FILE_DRAG_ROLE_TYPE_PREFIX}${role}`;
}

function storageFolderDragRoleType(role: FileRole) {
  return `${STORAGE_FOLDER_DRAG_ROLE_TYPE_PREFIX}${role}`;
}

function storageSelectionDragRoleType(role: FileRole) {
  return `${STORAGE_SELECTION_DRAG_ROLE_TYPE_PREFIX}${role}`;
}

function dataTransferTypes(dataTransfer: StorageDropDataTransfer) {
  return Array.from(dataTransfer.types || []).map((type) => String(type).toLowerCase());
}

function normalizeStorageFileDragPayload(payload: unknown): StorageFileDragPayload | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const role = normalizeRole(record.role);
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const fileId = normalizeRequiredText(record.file_id);
  const name = normalizeRequiredText(record.name);
  const previewKind = normalizePreviewKind(record.preview_kind);
  const relativePath = normalizeRequiredRelativePath(record.relative_path);
  const workspaceRelativePath = normalizeRequiredRelativePath(record.workspace_relative_path);

  if (!role || !ownerAppId || !fileId || !name || !relativePath || !workspaceRelativePath) {
    return null;
  }
  if (!workspaceRelativePath.startsWith(`storage/${role}/`)) {
    return null;
  }

  return {
    file_id: fileId,
    name,
    owner_app_id: ownerAppId,
    ...(previewKind ? { preview_kind: previewKind } : {}),
    relative_path: relativePath,
    role,
    workspace_relative_path: workspaceRelativePath,
  };
}

function normalizeStorageFolderDragPayload(payload: unknown): StorageFolderDragPayload | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const role = normalizeRole(record.role);
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const folderId = normalizeRequiredText(record.folder_id);
  const name = normalizeRequiredText(record.name);
  const relativePath = normalizeRequiredRelativePath(record.relative_path);
  const workspaceRelativePath = normalizeRequiredRelativePath(record.workspace_relative_path);

  if (!role || !ownerAppId || !folderId || !name || !relativePath || !workspaceRelativePath) {
    return null;
  }
  if (workspaceRelativePath !== `storage/${role}/${relativePath}`) {
    return null;
  }

  return {
    folder_id: folderId,
    name,
    owner_app_id: ownerAppId,
    relative_path: relativePath,
    role,
    workspace_relative_path: workspaceRelativePath,
  };
}

function normalizeStorageSelectionDragPayload(payload: unknown): StorageSelectionDragPayload | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  if (!ownerAppId) {
    return null;
  }

  const files = normalizePayloadList(record.files, normalizeStorageFileDragPayload);
  const folders = normalizePayloadList(record.folders, normalizeStorageFolderDragPayload);
  if (!files || !folders || (!files.length && !folders.length)) {
    return null;
  }
  if ([...files, ...folders].some((item) => item.owner_app_id !== ownerAppId)) {
    return null;
  }

  return {
    files,
    folders,
    owner_app_id: ownerAppId,
  };
}

function normalizeRole(value: unknown): FileRole | null {
  return value === 'uploaded' || value === 'generated' ? value : null;
}

function normalizePreviewKind(value: unknown): PreviewKind | null {
  return value === 'image'
    || value === 'video'
    || value === 'audio'
    || value === 'markdown'
    || value === 'text'
    || value === 'pdf'
    || value === 'document'
    || value === 'presentation'
    || value === 'spreadsheet'
    || value === 'file'
    ? value
    : null;
}

function normalizeRequiredText(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

function normalizeRequiredRelativePath(value: unknown) {
  if (typeof value !== 'string') {
    return '';
  }
  const parts = value.split('/').filter(Boolean);
  if (!parts.length) {
    return '';
  }
  if (parts.some((part) => part === '.' || part === '..')) {
    return '';
  }
  return parts.join('/');
}

function normalizePayloadList<T>(value: unknown, normalize: (item: unknown) => T | null): T[] | null {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value)) {
    return null;
  }
  const normalized = value.map((item) => normalize(item));
  if (normalized.some((item) => !item)) {
    return null;
  }
  return normalized as T[];
}

function storageSelectionRoles(payload: StorageSelectionDragPayload) {
  return Array.from(new Set([...payload.files.map((file) => file.role), ...payload.folders.map((folder) => folder.role)]));
}

function uniqueStorageFiles(files: StorageFile[]) {
  const byIdentity = new Map<string, StorageFile>();
  files.forEach((file) => byIdentity.set(`${file.role}:${file.relative_path}`, file));
  return Array.from(byIdentity.values());
}

function uniqueStorageFolders(folders: StorageFolder[]) {
  const byIdentity = new Map<string, StorageFolder>();
  folders.forEach((folder) => byIdentity.set(`${folder.role}:${folder.relative_path}`, folder));
  return Array.from(byIdentity.values());
}
