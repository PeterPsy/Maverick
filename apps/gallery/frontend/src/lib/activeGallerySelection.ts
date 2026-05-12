import type { GalleryFile } from '../types';

type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveGallerySelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveGallerySelection(file: GalleryFile, options: NotifyOptions = {}): boolean {
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? (typeof window === 'undefined' ? '*' : window.location.origin);
  parentWindow.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'gallery',
      selection: {
        file_id: file.id,
        workspace_relative_path: file.workspace_relative_path
      }
    },
    origin
  );
  return true;
}

export function gallerySelectionFromMessage(message: ActiveGallerySelectionMessage, ownerAppId = 'gallery') {
  if (message.type !== 'maverick.app.selection-changed' || message.owner_app_id !== ownerAppId) {
    return null;
  }
  const selection = message.selection;
  const fileId = selection && typeof selection.file_id === 'string' ? selection.file_id.trim() : '';
  const workspaceRelativePath = selection && typeof selection.workspace_relative_path === 'string' ? selection.workspace_relative_path.trim() : '';
  if (!fileId && !workspaceRelativePath) {
    return null;
  }
  return { fileId, workspaceRelativePath };
}
