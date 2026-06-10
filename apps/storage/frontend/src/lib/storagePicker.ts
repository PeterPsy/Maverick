import type { FileRole, PreviewKind, StorageFile } from '../types';
import { decodeParam, scalarString, type StorageNavigationParams } from './storageNavigationParams';

export type StoragePickerContext = {
  acceptedPreviewKinds: Array<'image' | 'video'>;
  mode: 'fitness-coach-media';
  returnAppId: 'fitness-coach';
};

export type StoragePickerSourceFolder =
  | {
      kind: 'local_folder';
      role: FileRole;
      folder_relative_path: string;
      workspace_relative_path: string;
      display_path: string;
    }
  | {
      kind: 'drive_folder';
      provider: 'google_drive';
      connection_id: string;
      drive_file_id: string;
      display_path: string;
    };

export type StoragePickerDriveFolderTarget = {
  connectionId: string;
  displayPath: string;
  driveFileId: string;
};

export type StoragePickerResult = {
  file: StorageFile;
  source_display_path: string | null;
  source_folder: StoragePickerSourceFolder | null;
};

const FITNESS_PICKER_MODE = 'fitness-coach-media';
const FITNESS_RETURN_APP_ID = 'fitness-coach';
const supportedPreviewKinds = new Set<PreviewKind>(['image', 'video']);

export function storagePickerContextFromParams(params: StorageNavigationParams): StoragePickerContext | null {
  const mode = scalarString(params.picker_mode);
  const returnAppId = scalarString(params.picker_return_app_id);
  if (mode !== FITNESS_PICKER_MODE || returnAppId !== FITNESS_RETURN_APP_ID) {
    return null;
  }
  const acceptedPreviewKinds = acceptedKindsFromParam(params.picker_accept);
  if (!acceptedPreviewKinds.length) {
    return null;
  }
  return {
    acceptedPreviewKinds,
    mode: FITNESS_PICKER_MODE,
    returnAppId: FITNESS_RETURN_APP_ID
  };
}

export function storagePickerAcceptsFile(context: StoragePickerContext, file: Pick<StorageFile, 'preview_kind'>) {
  return context.acceptedPreviewKinds.includes(file.preview_kind as 'image' | 'video');
}

export function storagePickerResultForFile(file: StorageFile, driveTarget: StoragePickerDriveFolderTarget | null): StoragePickerResult {
  const sourceFolder = storagePickerSourceFolderForFile(file, driveTarget);
  return {
    file,
    source_display_path: sourceFolder?.display_path || null,
    source_folder: sourceFolder
  };
}

function acceptedKindsFromParam(value: unknown): Array<'image' | 'video'> {
  const raw = scalarString(value) || 'video';
  const accepted = raw
    .split(',')
    .map((part) => decodeParam(part).trim())
    .filter((part): part is 'image' | 'video' => part === 'image' || part === 'video')
    .filter((part) => supportedPreviewKinds.has(part));
  return Array.from(new Set(accepted));
}

function storagePickerSourceFolderForFile(file: StorageFile, driveTarget: StoragePickerDriveFolderTarget | null): StoragePickerSourceFolder | null {
  if (file.provider === 'google_drive') {
    if (!driveTarget?.connectionId || !driveTarget.driveFileId) {
      return null;
    }
    if (file.connection_id && file.connection_id !== driveTarget.connectionId) {
      return null;
    }
    return {
      kind: 'drive_folder',
      provider: 'google_drive',
      connection_id: driveTarget.connectionId,
      drive_file_id: driveTarget.driveFileId,
      display_path: driveTarget.displayPath || 'Google Drive'
    };
  }
  if (file.role !== 'uploaded' && file.role !== 'generated') {
    return null;
  }
  const folderRelativePath = parentFolderPath(file.relative_path);
  const workspaceRelativePath = `storage/${file.role}${folderRelativePath ? `/${folderRelativePath}` : ''}`;
  return {
    kind: 'local_folder',
    role: file.role,
    folder_relative_path: folderRelativePath,
    workspace_relative_path: workspaceRelativePath,
    display_path: workspaceRelativePath
  };
}

function parentFolderPath(relativePath: string) {
  const parts = relativePath.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}
