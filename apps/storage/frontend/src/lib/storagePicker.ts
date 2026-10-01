import type { FileRole, PreviewKind, StorageFile } from '../types';
import { decodeParam, scalarString, type StorageNavigationParams } from './storageNavigationParams';

export type StoragePickerContext = {
  acceptedPreviewKinds: PreviewKind[];
  localOnly: boolean;
  mode: 'fitness-coach-media' | 'workspace-file';
  returnAppId: string;
  returnContext: string;
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
const WORKSPACE_FILE_PICKER_MODE = 'workspace-file';
const supportedPreviewKinds = new Set<PreviewKind>([
  'image',
  'video',
  'audio',
  'markdown',
  'text',
  'pdf',
  'document',
  'presentation',
  'spreadsheet',
  'file'
]);
const appIdPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function storagePickerContextFromParams(params: StorageNavigationParams): StoragePickerContext | null {
  const mode = scalarString(params.picker_mode);
  const returnAppId = scalarString(params.picker_return_app_id);
  const fitnessPicker = mode === FITNESS_PICKER_MODE && returnAppId === FITNESS_RETURN_APP_ID;
  const workspacePicker = mode === WORKSPACE_FILE_PICKER_MODE && appIdPattern.test(returnAppId);
  if (!fitnessPicker && !workspacePicker) {
    return null;
  }
  const acceptedPreviewKinds = acceptedKindsFromParam(params.picker_accept, workspacePicker ? 'any' : 'video');
  if (!acceptedPreviewKinds.length) {
    return null;
  }
  return {
    acceptedPreviewKinds,
    localOnly: workspacePicker && (params.picker_local_only === true || scalarString(params.picker_local_only) === 'true'),
    mode: fitnessPicker ? FITNESS_PICKER_MODE : WORKSPACE_FILE_PICKER_MODE,
    returnAppId,
    returnContext: scalarString(params.picker_context).slice(0, 200)
  };
}

export function storagePickerAcceptsFile(context: StoragePickerContext, file: Pick<StorageFile, 'preview_kind' | 'provider' | 'workspace_relative_path'>) {
  if (context.localOnly && (file.provider === 'google_drive' || !file.workspace_relative_path)) {
    return false;
  }
  return context.acceptedPreviewKinds.includes(file.preview_kind);
}

export function storagePickerResultForFile(file: StorageFile, driveTarget: StoragePickerDriveFolderTarget | null): StoragePickerResult {
  const sourceFolder = storagePickerSourceFolderForFile(file, driveTarget);
  return {
    file,
    source_display_path: sourceFolder?.display_path || null,
    source_folder: sourceFolder
  };
}

function acceptedKindsFromParam(value: unknown, fallback: string): PreviewKind[] {
  const raw = scalarString(value) || fallback;
  if (raw === 'any') {
    return Array.from(supportedPreviewKinds);
  }
  const accepted = raw
    .split(',')
    .map((part) => decodeParam(part).trim())
    .filter((part): part is PreviewKind => supportedPreviewKinds.has(part as PreviewKind))
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
