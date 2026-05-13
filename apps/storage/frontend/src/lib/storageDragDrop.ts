import type { FileRole, StorageFile } from '../types';

export const STORAGE_FILE_DRAG_DATA_TYPE = 'application/x-maverick-storage-file';

const STORAGE_FILE_DRAG_ROLE_TYPE_PREFIX = 'application/x-maverick-storage-file-role-';
const STORAGE_FILE_ROLES: FileRole[] = ['uploaded', 'generated'];

export type StorageFileDragPayload = {
  file_id: string;
  name: string;
  owner_app_id: string;
  relative_path: string;
  role: FileRole;
  workspace_relative_path: string;
};

export type StorageFileDropStatus = 'none' | 'ready' | 'blocked';

type StorageDragDataTransfer = Pick<DataTransfer, 'getData' | 'setData' | 'types'> & {
  effectAllowed?: DataTransfer['effectAllowed'];
};

type StorageDropDataTransfer = Pick<DataTransfer, 'types'>;

export function storageDragPayloadFromFile(file: StorageFile, ownerAppId: string): StorageFileDragPayload {
  return {
    file_id: file.file_id || file.id,
    name: file.name,
    owner_app_id: ownerAppId,
    relative_path: file.relative_path,
    role: file.role,
    workspace_relative_path: file.workspace_relative_path,
  };
}

export function writeStorageFileDragData(dataTransfer: StorageDragDataTransfer, payload: StorageFileDragPayload) {
  dataTransfer.setData(STORAGE_FILE_DRAG_DATA_TYPE, JSON.stringify(payload));
  dataTransfer.setData(storageFileDragRoleType(payload.role), payload.role);
  dataTransfer.effectAllowed = 'move';
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

export function storageFileDropStatus(dataTransfer: StorageDropDataTransfer, targetRole: FileRole | 'all'): StorageFileDropStatus {
  if (!hasStorageFileDragData(dataTransfer)) {
    return 'none';
  }
  if (targetRole === 'all') {
    return 'blocked';
  }
  const sourceRole = storageFileDragRole(dataTransfer);
  if (sourceRole && sourceRole !== targetRole) {
    return 'blocked';
  }
  return 'ready';
}

export function hasStorageFileDragData(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return types.includes(STORAGE_FILE_DRAG_DATA_TYPE) || types.some((type) => type.startsWith(STORAGE_FILE_DRAG_ROLE_TYPE_PREFIX));
}

function storageFileDragRole(dataTransfer: StorageDropDataTransfer) {
  const types = dataTransferTypes(dataTransfer);
  return STORAGE_FILE_ROLES.find((role) => types.includes(storageFileDragRoleType(role))) || null;
}

function storageFileDragRoleType(role: FileRole) {
  return `${STORAGE_FILE_DRAG_ROLE_TYPE_PREFIX}${role}`;
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
    relative_path: relativePath,
    role,
    workspace_relative_path: workspaceRelativePath,
  };
}

function normalizeRole(value: unknown): FileRole | null {
  return value === 'uploaded' || value === 'generated' ? value : null;
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
