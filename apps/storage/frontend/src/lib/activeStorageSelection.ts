import type { FileRole, StorageFile, StorageFolder } from '../types';
import type { StorageNavigationTarget } from './storageNavigationParams';

type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveStorageSelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveStorageSelection(file: StorageFile, options: NotifyOptions = {}): boolean {
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? (typeof window === 'undefined' ? '*' : window.location.origin);
  parentWindow.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'storage',
      selection: {
        file_id: file.id,
        workspace_relative_path: file.workspace_relative_path
      }
    },
    origin
  );
  return true;
}

export function notifyActiveStorageFolderSelection(folder: StorageFolder, options: NotifyOptions = {}): boolean {
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? (typeof window === 'undefined' ? '*' : window.location.origin);
  parentWindow.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'storage',
      selection: {
        folder_relative_path: folder.relative_path,
        role: folder.role,
        workspace_relative_path: folder.workspace_relative_path
      }
    },
    origin
  );
  return true;
}

export function storageSelectionFromMessage(message: ActiveStorageSelectionMessage, ownerAppId = 'storage'): StorageNavigationTarget | null {
  if (message.type !== 'maverick.app.selection-changed' || message.owner_app_id !== ownerAppId) {
    return null;
  }
  const selection = message.selection;
  const role = selectionRole(selection?.role);
  const hasFolderRelativePath = Boolean(selection && Object.prototype.hasOwnProperty.call(selection, 'folder_relative_path'));
  if (role && hasFolderRelativePath) {
    const folderRelativePath = typeof selection?.folder_relative_path === 'string' ? normalizeRelativePath(selection.folder_relative_path) : '';
    const workspaceRelativePath = typeof selection?.workspace_relative_path === 'string' ? selection.workspace_relative_path.trim() : '';
    return { fileId: '', folderRelativePath, role, targetType: 'folder', workspaceRelativePath };
  }
  const fileId = selection && typeof selection.file_id === 'string' ? selection.file_id.trim() : '';
  const workspaceRelativePath = selection && typeof selection.workspace_relative_path === 'string' ? selection.workspace_relative_path.trim() : '';
  if (!fileId && !workspaceRelativePath) {
    return null;
  }
  return { fileId, targetType: 'file', workspaceRelativePath };
}

function selectionRole(value: unknown): FileRole | null {
  return value === 'uploaded' || value === 'generated' ? value : null;
}

function normalizeRelativePath(value: string) {
  return value.split('/').filter(Boolean).join('/');
}
