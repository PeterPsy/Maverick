import { describe, expect, it } from 'vitest';
import type { StorageFile } from '../types';
import { storagePickerAcceptsFile, storagePickerContextFromParams, storagePickerResultForFile } from './storagePicker';

function storageFile(overrides: Partial<StorageFile> = {}): StorageFile {
  return {
    content_type: 'video/mp4',
    extension: '.mp4',
    file_id: 'file_1',
    id: 'file_1',
    modified_at: '2026-06-09T00:00:00Z',
    name: 'movement.mp4',
    path_id: 'file_1',
    preview_kind: 'video',
    relative_path: 'Mobility/movement.mp4',
    role: 'uploaded',
    sha256: 'sha',
    size_bytes: 10,
    workspace_relative_path: 'storage/uploaded/Mobility/movement.mp4',
    ...overrides
  };
}

describe('storage picker context', () => {
  it('activates only for Fitness Coach media picker params', () => {
    expect(storagePickerContextFromParams({
      picker_accept: 'video',
      picker_mode: 'fitness-coach-media',
      picker_return_app_id: 'fitness-coach'
    })).toEqual({
      acceptedPreviewKinds: ['video'],
      mode: 'fitness-coach-media',
      returnAppId: 'fitness-coach'
    });

    expect(storagePickerContextFromParams({})).toBeNull();
    expect(storagePickerContextFromParams({
      picker_mode: 'fitness-coach-media',
      picker_return_app_id: 'other-app'
    })).toBeNull();
  });

  it('limits selectable files to accepted preview kinds', () => {
    const context = storagePickerContextFromParams({
      picker_accept: 'video',
      picker_mode: 'fitness-coach-media',
      picker_return_app_id: 'fitness-coach'
    });

    expect(context).not.toBeNull();
    expect(storagePickerAcceptsFile(context!, storageFile())).toBe(true);
    expect(storagePickerAcceptsFile(context!, storageFile({ preview_kind: 'image', content_type: 'image/png', name: 'screenshot.png' }))).toBe(false);
  });

  it('returns local parent folder metadata with the selected file', () => {
    expect(storagePickerResultForFile(storageFile(), null).source_folder).toEqual({
      kind: 'local_folder',
      role: 'uploaded',
      folder_relative_path: 'Mobility',
      workspace_relative_path: 'storage/uploaded/Mobility',
      display_path: 'storage/uploaded/Mobility'
    });
  });

  it('returns current Drive folder metadata with a Drive file', () => {
    expect(storagePickerResultForFile(storageFile({
      connection_id: 'drive_conn',
      display_path: '/Il mio Drive/fitness-coach/Mobility/skandasana.mp4',
      drive_file_id: 'drive_file',
      provider: 'google_drive',
      relative_path: '',
      role: '',
      workspace_relative_path: ''
    }), {
      connectionId: 'drive_conn',
      displayPath: '/Il mio Drive/fitness-coach/Mobility',
      driveFileId: 'drive_folder'
    }).source_folder).toEqual({
      kind: 'drive_folder',
      provider: 'google_drive',
      connection_id: 'drive_conn',
      drive_file_id: 'drive_folder',
      display_path: '/Il mio Drive/fitness-coach/Mobility'
    });
  });

  it('does not attach a Drive folder from another connection', () => {
    expect(storagePickerResultForFile(storageFile({
      connection_id: 'drive_conn_other',
      drive_file_id: 'drive_file',
      provider: 'google_drive',
      relative_path: '',
      role: '',
      workspace_relative_path: ''
    }), {
      connectionId: 'drive_conn',
      displayPath: '/Il mio Drive/fitness-coach/Mobility',
      driveFileId: 'drive_folder'
    }).source_folder).toBeNull();
  });
});
