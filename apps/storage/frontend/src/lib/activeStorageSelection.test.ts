import { describe, expect, it, vi } from 'vitest';
import { notifyActiveStorageFolderSelection, storageSelectionFromMessage } from './activeStorageSelection';
import type { StorageFolder } from '../types';

describe('active storage selection messages', () => {
  it('round-trips Google Drive folders with provider identity', () => {
    const parentWindow = { postMessage: vi.fn() };
    const folder: StorageFolder = {
      id: 'folder_drive',
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'folder-1',
      display_path: '/My Drive/Clients',
      role: '',
      name: 'Clients',
      relative_path: '',
      workspace_relative_path: '',
      modified_at: '',
    };

    expect(notifyActiveStorageFolderSelection(folder, {
      currentWindow: {},
      origin: 'https://maverick.local',
      parentWindow,
    })).toBe(true);

    const [message] = parentWindow.postMessage.mock.calls[0];
    expect(message).toEqual({
      type: 'maverick.app.selection-changed',
      owner_app_id: 'storage',
      selection: {
        provider: 'google_drive',
        connection_id: 'drive_conn_1',
        drive_file_id: 'folder-1',
        display_path: '/My Drive/Clients',
      },
    });
    expect(storageSelectionFromMessage(message)).toEqual({
      connectionId: 'drive_conn_1',
      displayPath: '/My Drive/Clients',
      driveFileId: 'folder-1',
      fileId: '',
      folderRelativePath: '',
      provider: 'google_drive',
      role: 'all',
      targetType: 'folder',
      workspaceRelativePath: '',
    });
  });
});
