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

  it('does not preload Drive children from the folder row click', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');
    const nodeViewStart = source.indexOf('function FolderTreeNodeView');
    const triggerStart = source.indexOf('<TreeNodeTrigger', nodeViewStart);
    const triggerEnd = source.indexOf('<TreeExpander', triggerStart);
    expect(nodeViewStart).toBeGreaterThanOrEqual(0);
    expect(triggerStart).toBeGreaterThanOrEqual(0);
    expect(triggerEnd).toBeGreaterThan(triggerStart);
    const triggerSource = source.slice(triggerStart, triggerEnd);

    expect(triggerSource).toContain('onClick={() => onSelect(node)}');
    expect(triggerSource).not.toContain('onEnsureChildren(node)');
  });

  it('pauses Drive and view sync work while the app iframe is hidden', () => {
    const source = readSource('main.tsx');

    expect(source).toContain('const appVisibleRef = useRef(true);');
    expect(source).toContain("payload.type === 'maverick.app.visibility-changed'");
    expect(source).toContain('abortDriveRequests();');
    expect(source).toContain('!appVisibleRef.current || driveFolderAbortRef.current || driveLoadMoreAbortRef.current');
    expect(source).toContain('if (!appVisibleRef.current) {');
  });

  it('uses stable Drive folder ids across roots and navigation params', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');

    expect(source).toContain("return account || 'Google Drive';");
    expect(source).toContain("return `drive:${connectionId}:${driveFileId || 'root'}`;");
    expect(source).toContain('id: driveFolderIdentity(connectionId, folder.drive_file_id || folder.id),');
    expect(source).toContain('const displayPath = driveFolderDisplayPath(parentDisplayPath, folder);');
    expect(source).toContain('workspaceRelativePath: displayPath');
    expect(source).not.toContain('rootKind');
  });

  it('uses Drive and folder icons without expanding loaded empty Drive folders', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');

    expect(source).toContain('function GoogleDriveIcon');
    expect(source).toContain('if (node.id === STORAGE_ROOT_ID)');
    expect(source).toContain('return <Home className="h-4 w-4" />;');
    expect(source).toContain("return isDriveAccountNode(node) ? <GoogleDriveIcon className=\"h-4 w-4\" /> : undefined;");
    expect(source).toContain('hasChildren={true}');
    expect(source).toContain('const lazy = cached?.loaded');
    expect(source).toContain('? children.length > 0 || Boolean(cached.error)');
  });

  it('starts Drive breadcrumbs at the Drive account instead of Storage', () => {
    const source = readSource('main.tsx');

    expect(source).toContain('function driveBreadcrumbItems(displayPath: string)');
    expect(source).toContain("const driveBreadcrumbs = isDriveView ? driveBreadcrumbItems(driveTarget?.displayPath || 'Google Drive') : [];");
    expect(source).toContain('{isDriveView ? (');
    expect(source).toContain('aria-label={`Show ${item.label} root`}');
  });
});
