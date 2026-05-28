import type { FileRole } from '../types';

export type StorageNavigationParams = Record<string, string | boolean | null | undefined>;

export type StorageNavigationTarget = {
  connectionId?: string;
  displayPath?: string;
  driveFileId?: string;
  fileId: string;
  provider?: 'google_drive';
  workspaceRelativePath: string;
  targetType?: 'file' | 'folder';
  role?: FileRole | 'all';
  folderRelativePath?: string;
};

export type WidgetContextMessage = {
  context?: {
    content?: {
      payload?: unknown;
    };
  };
  type?: string;
};

export function scalarString(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

export function storageTargetFromParams(params: StorageNavigationParams): StorageNavigationTarget | null {
  const provider = scalarString(params.provider);
  if (provider === 'google_drive') {
    const connectionId = scalarString(params.connection_id);
    const driveFileId = scalarString(params.drive_file_id);
    if (!connectionId) {
      return null;
    }
    return {
      connectionId,
      displayPath: scalarString(params.display_path),
      driveFileId,
      fileId: '',
      folderRelativePath: '',
      provider: 'google_drive',
      role: 'all',
      targetType: 'folder',
      workspaceRelativePath: ''
    };
  }

  const role = storageRoleFromValue(params.role);
  if (role && hasOwn(params, 'folder_relative_path')) {
    return {
      fileId: '',
      folderRelativePath: normalizeRelativePath(params.folder_relative_path),
      role,
      targetType: 'folder',
      workspaceRelativePath: ''
    };
  }

  const fileId = scalarString(params.file_id);
  const workspaceRelativePath = scalarString(params.workspace_relative_path) || scalarString(params.path);
  if (fileId || workspaceRelativePath) {
    return { fileId, targetType: 'file', workspaceRelativePath };
  }
  const appPage = scalarString(params.app_page);
  const fileMatch = /^files\/(.+)$/.exec(appPage);
  if (fileMatch?.[1]) {
    return { fileId: decodeParam(fileMatch[1]), targetType: 'file', workspaceRelativePath: '' };
  }
  const folderMatch = /^folders\/(uploaded|generated)(?:\/(.*))?$/.exec(appPage);
  if (!folderMatch?.[1]) {
    return null;
  }
  const folderRole = storageRoleFromValue(folderMatch[1]);
  if (folderRole !== 'uploaded' && folderRole !== 'generated') {
    return null;
  }
  const folderRelativePath = normalizeRelativePath(decodeParam(folderMatch[2] || ''));
  return {
    fileId: '',
    folderRelativePath,
    role: folderRole,
    targetType: 'folder',
    workspaceRelativePath: `storage/${folderRole}${folderRelativePath ? `/${folderRelativePath}` : ''}`
  };
}

export function storageTargetFromWidgetContext(message: WidgetContextMessage): StorageNavigationTarget | null {
  if (message.type !== 'maverick.widget.context-changed') {
    return null;
  }
  const payload = message.context?.content?.payload;
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const activeAppId = scalarString((payload as { active_app_id?: unknown }).active_app_id);
  if (activeAppId !== 'storage') {
    return null;
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  if (!activeAppParams || typeof activeAppParams !== 'object' || Array.isArray(activeAppParams)) {
    return null;
  }
  return storageTargetFromParams(activeAppParams as StorageNavigationParams);
}

export function folderTargetFromMissingFileTarget(target: StorageNavigationTarget): StorageNavigationTarget | null {
  const workspaceRelativePath = scalarString(target.workspaceRelativePath);
  const match = /^storage\/(uploaded|generated)\/(.+)$/.exec(workspaceRelativePath);
  const role = storageRoleFromValue(match?.[1]);
  if ((role !== 'uploaded' && role !== 'generated') || !match?.[2]) {
    return null;
  }
  const pathParts = normalizeRelativePath(match[2]).split('/').filter(Boolean);
  pathParts.pop();
  const folderRelativePath = pathParts.join('/');
  return {
    fileId: '',
    folderRelativePath,
    role,
    targetType: 'folder',
    workspaceRelativePath: `storage/${role}${folderRelativePath ? `/${folderRelativePath}` : ''}`
  };
}

function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function storageRoleFromValue(value: unknown): FileRole | 'all' | null {
  const role = scalarString(value);
  if (role === 'all' || role === 'uploaded' || role === 'generated') {
    return role;
  }
  return null;
}

function hasOwn(params: StorageNavigationParams, key: string) {
  return Object.prototype.hasOwnProperty.call(params, key);
}

function normalizeRelativePath(value: unknown) {
  if (typeof value !== 'string') {
    return '';
  }
  return value.split('/').filter(Boolean).join('/');
}
