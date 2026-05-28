import { describe, expect, it } from 'vitest';
import { folderTargetFromMissingFileTarget, storageTargetFromParams } from './storageNavigationParams';

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
});
