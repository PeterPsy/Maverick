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

    expect(triggerSource).toContain('onClick={() => onSelect(node, ancestors)}');
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

  it('removes disconnected Drive accounts and does not spin the logout icon', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');
    const styles = readSource('styles/sidebar-widget.css');

    expect(source).toContain("connection.status !== 'pending' && connection.status !== 'disconnected'");
    expect(source).toContain("LogOut className={isDisconnecting ? 'is-breathing' : ''}");
    expect(source).not.toContain("LogOut className={isDisconnecting ? 'is-spinning' : ''}");
    expect(styles).toContain('.storage-folder-tree-sync .is-breathing');
    expect(styles).toContain('@keyframes storage-sidebar-breathe');
  });

  it('starts Drive breadcrumbs at the Drive account instead of Storage', () => {
    const source = readSource('main.tsx');

    expect(source).toContain("import { driveBreadcrumbItems, driveBreadcrumbTargetsFromInput, driveBreadcrumbTrailForFolder, driveBreadcrumbTrailForTarget, type DriveBreadcrumbTarget } from './lib/storageDriveBreadcrumbs';");
    expect(source).toContain('function driveTargetWithBreadcrumbDisplayPath(target: DriveFolderTarget, trail: DriveBreadcrumbTarget[])');
    expect(source).toContain("const driveBreadcrumbs = isDriveView ? driveBreadcrumbItems(driveTarget?.displayPath || 'Google Drive', driveBreadcrumbTrail) : [];");
    expect(source).toContain('const payloadBreadcrumbTrail = driveBreadcrumbTargetsFromInput(payload.breadcrumbs, target.connectionId);');
    expect(source).toContain('breadcrumbTrail ?? (payloadBreadcrumbTrail.length ? payloadBreadcrumbTrail : driveBreadcrumbTrailForTarget(target, driveBreadcrumbTrailRef.current));');
    expect(source).toContain('const nextDriveTarget = driveTargetWithBreadcrumbDisplayPath(target, nextBreadcrumbTrail);');
    expect(source).toContain("loadDriveFolder(nextTarget, 'foreground', target.driveBreadcrumbs)");
    expect(source).toContain('{isDriveView ? (');
    expect(source).toContain("const canNavigate = Boolean(!isCurrent && driveTarget?.connectionId && (item.driveFileId || index === 0));");
    expect(source).toContain("const nextTrail = target.driveFileId ? driveBreadcrumbTrailForTarget(target, driveBreadcrumbTrailRef.current) : [];");
  });

  it('passes resolved Drive breadcrumb ids from sidebar folder selection', () => {
    const source = readSource('widgets/storage-sidebar/main.tsx');

    expect(source).toContain("import type { DriveBreadcrumbTarget } from '../../lib/storageDriveBreadcrumbs';");
    expect(source).toContain('function openFolderInShell(node: FolderTreeNode, appId: string, ancestors: FolderTreeNode[] = [])');
    expect(source).toContain("...driveBreadcrumbNavigationParams([...ancestors, node]),");
    expect(source).toContain('function driveBreadcrumbTargetsFromNodes(nodes: FolderTreeNode[]): DriveBreadcrumbTarget[]');
    expect(source).toContain('onClick={() => onSelect(node, ancestors)}');
    expect(source).toContain('ancestors={childAncestors}');
  });

  it('drags Drive files and folders as Storage references instead of blocking the drag', () => {
    const source = readSource('main.tsx');
    const fileCollectionSource = readSource('components/ui/animated-collection.tsx');

    expect(source).toContain('storageDriveDragPayloadFromFile');
    expect(source).toContain('writeStorageDriveFileDragData(event.dataTransfer, payload);');
    expect(source).toContain('storageDriveDragPayloadFromFolder');
    expect(source).toContain('writeStorageDriveFolderDragData(event.dataTransfer, payload);');
    expect(source).toContain('canDrag={isDriveItem(folder) ? Boolean(folder.connection_id && folder.drive_file_id) : Boolean(folder.relative_path)}');
    expect(fileCollectionSource).toContain('const canDrag = file.provider === "google_drive" ? Boolean(file.connection_id && file.drive_file_id) : canMove;');
    expect(fileCollectionSource).toContain('draggable={canDrag}');
    expect(source).not.toContain('if (isDriveItem(file)) {\n      event.preventDefault();\n      return 0;\n    }');
  });
});
