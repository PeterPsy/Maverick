import { describe, expect, it } from 'vitest';
import { storageTargetFromParams } from './storageNavigationParams';

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
});
