import { describe, expect, it } from 'vitest';
import { folderTargetFromMissingFileTarget, storageFolderTargetMatchesLocalView, storageTargetFromParams } from './storageNavigationParams';

describe('storage navigation params', () => {
  it('parses folder deep links from app page params', () => {
    expect(storageTargetFromParams({ app_page: 'folders/generated/Client%20Docs/Q1' })).toEqual({
      fileId: '',
      folderRelativePath: 'Client Docs/Q1',
      role: 'generated',
      targetType: 'folder',
      workspaceRelativePath: 'storage/generated/Client Docs/Q1'
    });
  });

  it('parses storage root folder deep links', () => {
    expect(storageTargetFromParams({ app_page: 'folders/uploaded' })).toEqual({
      fileId: '',
      folderRelativePath: '',
      role: 'uploaded',
      targetType: 'folder',
      workspaceRelativePath: 'storage/uploaded'
    });
  });

  it('parses Google Drive folder navigation without workspace identity', () => {
    expect(storageTargetFromParams({
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'folder-1',
      display_path: '/My Drive/Clients'
    })).toEqual({
      connectionId: 'drive_conn_1',
      displayPath: '/My Drive/Clients',
      driveFileId: 'folder-1',
      fileId: '',
      folderRelativePath: '',
      provider: 'google_drive',
      role: 'all',
      targetType: 'folder',
      workspaceRelativePath: ''
    });
  });

  it('parses Google Drive breadcrumb targets from navigation params', () => {
    expect(storageTargetFromParams({
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'folder-reports',
      display_path: '/My Drive/Clients/Reports',
      drive_breadcrumbs: JSON.stringify([
        {
          connection_id: 'drive_conn_1',
          display_path: '/My Drive',
          drive_file_id: 'root',
          label: 'My Drive',
        },
        {
          connection_id: 'drive_conn_1',
          display_path: '/My Drive/Clients',
          drive_file_id: 'folder-clients',
          label: 'Clients',
        },
      ]),
    })).toEqual({
      connectionId: 'drive_conn_1',
      displayPath: '/My Drive/Clients/Reports',
      driveBreadcrumbs: [
        {
          connectionId: 'drive_conn_1',
          displayPath: '/My Drive',
          driveFileId: 'root',
          label: 'My Drive',
          path: '/My Drive',
        },
        {
          connectionId: 'drive_conn_1',
          displayPath: '/My Drive/Clients',
          driveFileId: 'folder-clients',
          label: 'Clients',
          path: '/My Drive/Clients',
        },
      ],
      driveFileId: 'folder-reports',
      fileId: '',
      folderRelativePath: '',
      provider: 'google_drive',
      role: 'all',
      targetType: 'folder',
      workspaceRelativePath: ''
    });
  });

  it('falls back from a missing file target to its parent folder', () => {
    expect(folderTargetFromMissingFileTarget({
      fileId: '',
      targetType: 'file',
      workspaceRelativePath: 'storage/uploaded/Receipts/invoice.png'
    })).toEqual({
      fileId: '',
      folderRelativePath: 'Receipts',
      role: 'uploaded',
      targetType: 'folder',
      workspaceRelativePath: 'storage/uploaded/Receipts'
    });
    expect(folderTargetFromMissingFileTarget({
      fileId: '',
      targetType: 'file',
      workspaceRelativePath: 'storage/generated/report.md'
    })).toEqual({
      fileId: '',
      folderRelativePath: '',
      role: 'generated',
      targetType: 'folder',
      workspaceRelativePath: 'storage/generated'
    });
  });

  it('recognizes an already-open local folder without treating other views as equivalent', () => {
    const target = storageTargetFromParams({
      role: 'generated',
      folder_relative_path: '/reading//',
    });
    expect(target).not.toBeNull();
    expect(storageFolderTargetMatchesLocalView(target!, {
      activeRole: 'generated',
      currentFolderPath: 'reading',
      driveActive: false,
      query: '',
      viewMode: 'search',
    })).toBe(true);
    expect(storageFolderTargetMatchesLocalView(target!, {
      activeRole: 'generated',
      currentFolderPath: 'reading',
      driveActive: false,
      query: 'report',
      viewMode: 'search',
    })).toBe(false);
    expect(storageFolderTargetMatchesLocalView(target!, {
      activeRole: 'generated',
      currentFolderPath: 'reading',
      driveActive: false,
      query: '',
      viewMode: 'custom',
    })).toBe(false);
    expect(storageFolderTargetMatchesLocalView(target!, {
      activeRole: 'generated',
      currentFolderPath: 'reading',
      driveActive: true,
      query: '',
      viewMode: 'search',
    })).toBe(false);
  });
});
