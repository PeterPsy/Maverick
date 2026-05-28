import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage Drive navigation stability', () => {
  it('keeps the Drive target ref current while folder navigation refreshes', () => {
    const source = readSource('main.tsx');
    const loadDriveStart = source.indexOf('async function loadDriveFolder');
    const catalogRequestStart = source.indexOf('function catalogRequest');
    expect(loadDriveStart).toBeGreaterThanOrEqual(0);
    expect(catalogRequestStart).toBeGreaterThan(loadDriveStart);
    const loadDriveBody = source.slice(loadDriveStart, catalogRequestStart);

    expect(loadDriveBody).toContain('const previousDriveTarget = driveTargetRef.current;');
    expect(loadDriveBody).toContain('driveTargetRef.current = target;');
    expect(loadDriveBody).toContain('driveTargetRef.current = previousDriveTarget;');
  });

  it('does not remount the sidebar tree on folder-count changes', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');

    expect(source).toContain("const treeProviderKey = query.trim().toLowerCase() || 'tree';");
    expect(source).toContain('toggleOnTriggerClick={false}');
    expect(source).toContain('return [storageRoot, ...driveRoots];');
    expect(source).not.toContain("`${query.trim().toLowerCase() || 'tree'}:${folders.length}`");
  });

  it('uses stable Drive folder ids across roots and navigation params', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');

    expect(source).toContain("return account ? `Google Drive - ${account}` : 'Google Drive';");
    expect(source).toContain("return `drive:${connectionId}:${driveFileId || 'root'}`;");
    expect(source).toContain('id: driveFolderIdentity(connectionId, folder.drive_file_id || folder.id),');
    expect(source).not.toContain('rootKind');
  });

  it('uses Drive and folder icons without expanding loaded empty Drive folders', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');

    expect(source).toContain('function GoogleDriveIcon');
    expect(source).toContain("return isDriveAccountNode(node) ? <GoogleDriveIcon className=\"h-4 w-4\" /> : undefined;");
    expect(source).toContain('hasChildren={true}');
    expect(source).toContain('const lazy = cached?.loaded');
    expect(source).toContain('? children.length > 0 || Boolean(cached.error)');
  });
});
