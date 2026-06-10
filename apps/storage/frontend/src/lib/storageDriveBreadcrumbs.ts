import type { StorageFolder } from '../types';

const MY_DRIVE_ROOT_ID = 'root';
const MY_DRIVE_ROOT_LABEL = 'My Drive';
const MY_DRIVE_ROOT_ALIASES = new Set(['my drive', 'il mio drive']);
const SHARED_WITH_ME_ROOT_ID = 'sharedWithMe';

export type DriveBreadcrumbTarget = {
  connectionId?: string;
  displayPath: string;
  driveFileId?: string;
  label: string;
  path: string;
};

export type DriveFolderTargetInput = {
  connectionId: string;
  displayPath: string;
  driveFileId: string;
};

export function driveBreadcrumbItems(displayPath: string, trail: DriveBreadcrumbTarget[] = []): DriveBreadcrumbTarget[] {
  const labels = drivePathLabels(displayPath);
  const trailByPath = new Map(trail.map((item) => [normalizeDriveDisplayPath(item.displayPath), item]));
  return labels.map((label, index) => {
    const path = `/${labels.slice(0, index + 1).join('/')}`;
    const existing = trailByPath.get(path);
    return existing
      ? { ...existing, label, path, displayPath: path }
      : { label, path, displayPath: path };
  });
}

export function driveBreadcrumbTargetsFromInput(value: unknown, fallbackConnectionId: string): DriveBreadcrumbTarget[] {
  const parsed = parsedDriveBreadcrumbInput(value);
  if (!Array.isArray(parsed)) {
    return [];
  }
  const targets: DriveBreadcrumbTarget[] = [];
  const seenPaths = new Set<string>();
  for (const item of parsed) {
    const target = driveBreadcrumbTargetFromRecord(item, fallbackConnectionId);
    if (!target || seenPaths.has(target.displayPath)) {
      continue;
    }
    seenPaths.add(target.displayPath);
    targets.push(target);
  }
  return targets;
}

export function driveBreadcrumbTrailForFolder(folder: StorageFolder, currentTrail: DriveBreadcrumbTarget[]): DriveBreadcrumbTarget[] {
  const item = driveBreadcrumbTargetFromFolder(folder);
  if (!item) {
    return currentTrail;
  }
  return driveBreadcrumbTrailWithTarget(item, currentTrail);
}

export function driveBreadcrumbTrailForTarget(target: DriveFolderTargetInput, currentTrail: DriveBreadcrumbTarget[]): DriveBreadcrumbTarget[] {
  if (!target.driveFileId) {
    return [];
  }
  const item = driveBreadcrumbTargetFromTarget(target);
  return driveBreadcrumbTrailWithTarget(item, currentTrail);
}

function driveBreadcrumbTrailWithTarget(target: DriveBreadcrumbTarget, currentTrail: DriveBreadcrumbTarget[]) {
  const existingIndex = currentTrail.findIndex((item) => sameDriveBreadcrumbTarget(item, target));
  if (existingIndex >= 0) {
    return currentTrail.slice(0, existingIndex + 1);
  }

  const parentPath = parentDriveDisplayPath(target.displayPath);
  const parentIndex = currentTrail.findIndex((item) => normalizeDriveDisplayPath(item.displayPath) === parentPath);
  if (parentIndex >= 0) {
    return [...currentTrail.slice(0, parentIndex + 1), target];
  }

  const root = inferredRootTarget(target.connectionId, target.displayPath);
  if (!root || normalizeDriveDisplayPath(root.displayPath) === normalizeDriveDisplayPath(target.displayPath)) {
    return [target];
  }
  return [root, target];
}

function driveBreadcrumbTargetFromFolder(folder: StorageFolder): DriveBreadcrumbTarget | null {
  const connectionId = text(folder.connection_id);
  const driveFileId = text(folder.drive_file_id);
  const displayPath = normalizeDriveDisplayPath(folder.display_path) || normalizeDriveDisplayPath(folder.name);
  if (folder.provider !== 'google_drive' || !connectionId || !driveFileId || !displayPath) {
    return null;
  }
  return {
    connectionId,
    displayPath,
    driveFileId,
    label: drivePathLabel(displayPath),
    path: displayPath,
  };
}

function driveBreadcrumbTargetFromTarget(target: DriveFolderTargetInput): DriveBreadcrumbTarget {
  const displayPath = normalizeDriveDisplayPath(target.displayPath) || '/Google Drive';
  return {
    connectionId: target.connectionId,
    displayPath,
    driveFileId: target.driveFileId,
    label: drivePathLabel(displayPath),
    path: displayPath,
  };
}

function parsedDriveBreadcrumbInput(value: unknown) {
  if (typeof value !== 'string') {
    return value;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return [];
  }
}

function driveBreadcrumbTargetFromRecord(value: unknown, fallbackConnectionId: string): DriveBreadcrumbTarget | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const connectionId = text(record.connectionId) || text(record.connection_id) || fallbackConnectionId;
  const driveFileId = text(record.driveFileId) || text(record.drive_file_id);
  const displayPath = normalizeDriveDisplayPath(text(record.displayPath) || text(record.display_path) || text(record.path));
  if (!connectionId || connectionId !== fallbackConnectionId || !driveFileId || !displayPath) {
    return null;
  }
  return {
    connectionId,
    displayPath,
    driveFileId,
    label: drivePathLabel(displayPath),
    path: displayPath,
  };
}

function inferredRootTarget(connectionId: string | undefined, displayPath: string): DriveBreadcrumbTarget | null {
  const labels = drivePathLabels(displayPath);
  const [rootLabel, secondLabel] = labels;
  if (!connectionId || !rootLabel) {
    return null;
  }
  if (rootLabel === 'My Drive') {
    return {
      connectionId,
      displayPath: `/${MY_DRIVE_ROOT_LABEL}`,
      driveFileId: MY_DRIVE_ROOT_ID,
      label: MY_DRIVE_ROOT_LABEL,
      path: `/${MY_DRIVE_ROOT_LABEL}`,
    };
  }
  if (rootLabel === 'Shared with me') {
    return {
      connectionId,
      displayPath: '/Shared with me',
      driveFileId: SHARED_WITH_ME_ROOT_ID,
      label: rootLabel,
      path: '/Shared with me',
    };
  }
  if (rootLabel === 'Shared drives' && secondLabel) {
    return {
      connectionId,
      displayPath: `/Shared drives/${secondLabel}`,
      label: secondLabel,
      path: `/Shared drives/${secondLabel}`,
    };
  }
  return null;
}

function sameDriveBreadcrumbTarget(left: DriveBreadcrumbTarget, right: DriveBreadcrumbTarget) {
  return Boolean(
    left.connectionId
      && right.connectionId
      && left.driveFileId
      && right.driveFileId
      && left.connectionId === right.connectionId
      && left.driveFileId === right.driveFileId
  );
}

function drivePathLabels(displayPath: string) {
  const parts = normalizeDriveDisplayPath(displayPath).split('/').filter(Boolean);
  return parts.length ? parts : ['Google Drive'];
}

function drivePathLabel(displayPath: string) {
  const labels = drivePathLabels(displayPath);
  return labels[labels.length - 1] || 'Google Drive';
}

function parentDriveDisplayPath(displayPath: string) {
  const labels = drivePathLabels(displayPath);
  labels.pop();
  return labels.length ? `/${labels.join('/')}` : '';
}

function normalizeDriveDisplayPath(value: string | undefined) {
  const parts = String(value || '').split('/').filter(Boolean);
  if (!parts.length || parts.some((part) => part === '.' || part === '..')) {
    return '';
  }
  const [rootLabel, ...rest] = parts;
  const normalizedRootLabel = MY_DRIVE_ROOT_ALIASES.has(rootLabel.toLocaleLowerCase()) ? MY_DRIVE_ROOT_LABEL : rootLabel;
  return `/${[normalizedRootLabel, ...rest].join('/')}`;
}

function text(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}
