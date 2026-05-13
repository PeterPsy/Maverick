import type { FileRole } from '../types';

export type StorageNavigationParams = Record<string, string | boolean | null | undefined>;

export type StorageNavigationTarget = {
  fileId: string;
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
  const match = /^files\/(.+)$/.exec(appPage);
  if (!match?.[1]) {
    return null;
  }
  return { fileId: decodeParam(match[1]), targetType: 'file', workspaceRelativePath: '' };
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
