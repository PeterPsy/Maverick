import { useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent, type PointerEvent, type SVGProps } from 'react';
import { createRoot } from 'react-dom/client';
import { Home, LogOut, RefreshCw } from 'lucide-react';
import {
  TreeExpander,
  TreeIcon,
  TreeLabel,
  TreeNode,
  TreeNodeContent,
  TreeNodeTrigger,
  TreeProvider,
  TreeView,
} from '../../components/ui/tree';
import { FileCard } from '../../components/ui/file-card-collections';
import { DRIVE_PAGE_LIMIT, currentStorageAppId, disconnectDriveConnection, listDriveChildren, listDriveConnections, listDriveRoots, loadCatalog, loadViewFilter, moveFileReference, moveFolderReference, moveItemsReferences, setViewFilter, syncDriveConnection } from '../../storageApi';
import { kindLabels, roleLabels } from '../../storageMeta';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { storageSelectionFromMessage, type ActiveStorageSelectionMessage } from '../../lib/activeStorageSelection';
import { applyStorageFoldersDelta, type StorageCatalogDelta } from '../../lib/storageCatalogDelta';
import { attachStorageFolderDragImage } from '../../lib/storageDragImage';
import { readStorageFileDragData, readStorageFolderDragData, readStorageSelectionDragData, storageDragPayloadFromFolder, storageMoveDropStatus, writeStorageFolderDragData, type StorageMoveDropStatus, type StorageSelectionDragPayload } from '../../lib/storageDragDrop';
import type { DriveBreadcrumbTarget } from '../../lib/storageDriveBreadcrumbs';
import { storageTargetFromWidgetContext, type StorageNavigationTarget } from '../../lib/storageNavigationParams';
import { storageViewFilterChangedMessage, storageViewFilterFromMessage } from '../../lib/storageViewFilterEvents';
import type { DriveConnection, FileRole, StorageFolder, StorageViewFilter, PreviewKind } from '../../types';
import '../../styles/sidebar-widget.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';
const STORAGE_ROOT_ID = 'folder:all:/';
const STORAGE_ROLES: FileRole[] = ['uploaded', 'generated'];
const VIEW_KINDS = new Set<PreviewKind | 'all'>(['all', 'image', 'video', 'audio', 'pdf', 'document', 'presentation', 'spreadsheet', 'markdown', 'text', 'file']);
const UPLOAD_BUCKET_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type StorageTreeRole = FileRole | 'all';
type FileCardFormat = 'doc' | 'pdf' | 'md' | 'xls' | 'txt' | 'ppt' | 'img' | 'video' | 'audio' | 'zip' | 'code';

type KindFilterOption = {
  formats: FileCardFormat[];
  kind: PreviewKind | 'all';
  label: string;
};

type KindRailDragState = {
  dragged: boolean;
  pointerId: number;
  scrollLeft: number;
  startX: number;
};

type FolderTreeDropTarget = {
  nodeId: string;
  status: Exclude<StorageMoveDropStatus, 'none'>;
};

const KIND_FILTER_OPTIONS: KindFilterOption[] = [
  { kind: 'all', label: 'All', formats: ['pdf', 'img', 'code'] },
  { kind: 'image', label: `${kindLabels.image}s`, formats: ['img'] },
  { kind: 'video', label: `${kindLabels.video}s`, formats: ['video'] },
  { kind: 'audio', label: kindLabels.audio, formats: ['audio'] },
  { kind: 'pdf', label: `${kindLabels.pdf}s`, formats: ['pdf'] },
  { kind: 'document', label: 'Docs', formats: ['doc'] },
  { kind: 'presentation', label: 'Slides', formats: ['ppt'] },
  { kind: 'spreadsheet', label: 'Sheets', formats: ['xls'] },
  { kind: 'markdown', label: kindLabels.markdown, formats: ['md'] },
  { kind: 'text', label: kindLabels.text, formats: ['txt'] },
  { kind: 'file', label: 'Other', formats: ['zip'] }
];

type ViewFilterPayload = {
  state?: {
    view_filter?: StorageViewFilter;
  };
};

type FolderTreeNode = {
  children: FolderTreeNode[];
  connectionId?: string;
  displayPath?: string;
  driveFileId?: string;
  error?: string;
  id: string;
  label: string;
  lazy?: boolean;
  loading?: boolean;
  provider: 'local' | 'google_drive';
  relativePath: string;
  role: StorageTreeRole;
  status?: DriveConnection['status'] | 'reconnect_required';
  workspaceRelativePath: string;
};

type DriveChildrenCache = Record<string, {
  children: FolderTreeNode[];
  error?: string;
  loading?: boolean;
  loaded?: boolean;
}>;

function isMobileLayoutViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

function useShellMobileLayout() {
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    let mediaQuery: MediaQueryList;
    try {
      const shellWindow = window.parent && window.parent !== window ? window.parent : window;
      mediaQuery = shellWindow.matchMedia(MOBILE_LAYOUT_QUERY);
    } catch {
      mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
    }
    const update = () => setIsShellMobileLayout(mediaQuery.matches);
    update();
    mediaQuery.addEventListener('change', update);
    return () => mediaQuery.removeEventListener('change', update);
  }, []);

  return isShellMobileLayout;
}

function folderIdentity(role: StorageTreeRole, relativePath: string) {
  return `folder:${role}:${relativePath || '/'}`;
}

function driveAccountIdentity(connectionId: string) {
  return `drive:${connectionId}`;
}

function driveFolderIdentity(connectionId: string, driveFileId: string) {
  return `drive:${connectionId}:${driveFileId || 'root'}`;
}

function normalizeFolderPath(path: string) {
  return path.split('/').filter(Boolean).join('/');
}

function isFileRole(role: unknown): role is FileRole {
  return role === 'uploaded' || role === 'generated';
}

function folderMoveTargetBlocked(source: Pick<StorageFolder, 'relative_path' | 'role'>, target: FolderTreeNode) {
  if (target.provider !== 'local' || target.role === 'all' || source.role !== target.role) {
    return true;
  }
  const sourcePath = normalizeFolderPath(source.relative_path);
  const targetPath = normalizeFolderPath(target.relativePath);
  if (!sourcePath) {
    return true;
  }
  return targetPath === sourcePath || targetPath.startsWith(`${sourcePath}/`);
}

function folderContainsPath(folder: Pick<StorageFolder, 'relative_path'>, relativePath: string) {
  const folderPath = normalizeFolderPath(folder.relative_path);
  const childPath = normalizeFolderPath(relativePath);
  return Boolean(folderPath) && (childPath === folderPath || childPath.startsWith(`${folderPath}/`));
}

function storageSelectionMoveTargetBlocked(selection: StorageSelectionDragPayload, target: FolderTreeNode) {
  return selection.files.some((file) => file.role !== target.role)
    || selection.folders.some((folder) => folder.role !== target.role || folderMoveTargetBlocked(folder, target));
}

function storageSelectionMovePlan(selection: StorageSelectionDragPayload) {
  const movableFolders = selection.folders.filter((folder) => !selection.folders.some((parent) => (
    parent.folder_id !== folder.folder_id
    && parent.role === folder.role
    && folderContainsPath(parent, folder.relative_path)
  )));
  const movableFiles = selection.files.filter((file) => !movableFolders.some((folder) => folder.role === file.role && folderContainsPath(folder, file.relative_path)));
  return { files: movableFiles, folders: movableFolders };
}

function storageFolderFromNode(node: FolderTreeNode): StorageFolder | null {
  if (node.provider !== 'local' || node.role === 'all' || !node.relativePath) {
    return null;
  }
  return {
    id: `${node.role}:${node.relativePath}/`,
    modified_at: '',
    name: node.label,
    relative_path: node.relativePath,
    role: node.role,
    workspace_relative_path: node.workspaceRelativePath,
  };
}

function buildFolderTree(folders: StorageFolder[]): FolderTreeNode {
  const uploadedRoot: FolderTreeNode = {
    children: [],
    id: folderIdentity('uploaded', ''),
    label: roleLabels.uploaded,
    provider: 'local',
    relativePath: '',
    role: 'uploaded',
    workspaceRelativePath: 'storage/uploaded'
  };
  const generatedRoot: FolderTreeNode = {
    children: [],
    id: folderIdentity('generated', ''),
    label: roleLabels.generated,
    provider: 'local',
    relativePath: '',
    role: 'generated',
    workspaceRelativePath: 'storage/generated'
  };
  const root: FolderTreeNode = {
    children: [uploadedRoot, generatedRoot],
    id: STORAGE_ROOT_ID,
    label: 'Storage',
    provider: 'local',
    relativePath: '',
    role: 'all',
    workspaceRelativePath: 'storage'
  };
  const roleRoots: Record<FileRole, FolderTreeNode> = {
    generated: generatedRoot,
    uploaded: uploadedRoot
  };

  folders
    .slice()
    .filter((folder): folder is StorageFolder & { role: FileRole } => isFileRole(folder.role))
    .sort((left, right) => `${left.role}/${left.relative_path}`.localeCompare(`${right.role}/${right.relative_path}`))
    .forEach((folder) => {
      const folderPath = normalizeFolderPath(folder.relative_path);
      if (!folderPath) {
        return;
      }
      const parts = folderPath.split('/');
      let current = roleRoots[folder.role];
      let currentPath = '';

      parts.forEach((part) => {
        currentPath = currentPath ? `${currentPath}/${part}` : part;
        let child = current.children.find((node) => node.relativePath === currentPath);
        if (!child) {
          child = {
            children: [],
            id: folderIdentity(folder.role, currentPath),
            label: part,
            provider: 'local',
            relativePath: currentPath,
            role: folder.role,
            workspaceRelativePath: `storage/${folder.role}/${currentPath}`
          };
          current.children.push(child);
        }
        if (currentPath === folderPath) {
          child.label = folder.name;
          child.workspaceRelativePath = folder.workspace_relative_path;
        }
        current = child;
      });
    });

  sortFolderTree(root);
  return root;
}

function buildDriveTreeNodes(connections: DriveConnection[], cache: DriveChildrenCache): FolderTreeNode[] {
  return connections
    .filter((connection) => connection.status !== 'pending' && connection.status !== 'disconnected')
    .slice()
    .sort((left, right) => driveConnectionLabel(left).localeCompare(driveConnectionLabel(right)))
    .map((connection) => {
      const nodeId = driveAccountIdentity(connection.id);
      const cached = cache[nodeId];
      const status = driveConnectionStatus(connection);
      return {
        children: cached?.children || [],
        connectionId: connection.id,
        displayPath: driveConnectionLabel(connection),
        error: cached?.error,
        id: nodeId,
        label: driveConnectionLabel(connection),
        lazy: status === 'connected',
        loading: cached?.loading,
        provider: 'google_drive',
        relativePath: '',
        role: 'all',
        status,
        workspaceRelativePath: connection.account_email || connection.id
      };
    });
}

function driveConnectionLabel(connection: DriveConnection) {
  const account = connection.account_email || connection.display_name;
  return account || 'Google Drive';
}

function driveConnectionStatus(connection: DriveConnection): FolderTreeNode['status'] {
  if (connection.status !== 'connected') {
    return connection.status;
  }
  return connection.credential?.secret_ref && connection.credential?.status === 'active' ? 'connected' : 'reconnect_required';
}

function GoogleDriveIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 24 24" {...props}>
      <path d="M8.2 4h7.6l4.2 7.2h-7.7L8.2 4Z" fill="#0F9D58" />
      <path d="M8.2 4 4 11.2 7.9 18l4.3-7.1L8.2 4Z" fill="#F4B400" />
      <path d="M7.9 18h8.2l3.9-6.8h-7.7L7.9 18Z" fill="#4285F4" />
    </svg>
  );
}

function isDriveAccountNode(node: FolderTreeNode) {
  return node.provider === 'google_drive' && !node.driveFileId;
}

function folderTreeIcon(node: FolderTreeNode) {
  if (node.id === STORAGE_ROOT_ID) {
    return <Home className="h-4 w-4" />;
  }
  return isDriveAccountNode(node) ? <GoogleDriveIcon className="h-4 w-4" /> : undefined;
}

function normalizeDriveDisplayPath(path: string) {
  return path.split('/').filter(Boolean).join('/');
}

function driveFolderDisplayPath(parentDisplayPath: string | undefined, folder: StorageFolder) {
  const parent = normalizeDriveDisplayPath(parentDisplayPath || '');
  const remotePath = normalizeDriveDisplayPath(folder.display_path || '');
  if (remotePath) {
    const [account, ...parentRemoteParts] = parent.split('/').filter(Boolean);
    if (account) {
      if (remotePath === account || remotePath.startsWith(`${account}/`)) {
        return remotePath;
      }
      const parentRemotePath = parentRemoteParts.join('/');
      if (!parentRemotePath || remotePath === parentRemotePath || remotePath.startsWith(`${parentRemotePath}/`)) {
        return `${account}/${remotePath}`;
      }
    }
    return remotePath;
  }
  const name = normalizeDriveDisplayPath(folder.name);
  if (!parent) {
    return name;
  }
  return name ? `${parent}/${name}` : parent;
}

function driveFolderNode(connectionId: string, folder: StorageFolder, parentDisplayPath?: string): FolderTreeNode {
  const displayPath = driveFolderDisplayPath(parentDisplayPath, folder);
  return {
    children: [],
    connectionId,
    displayPath,
    driveFileId: folder.drive_file_id || '',
    id: driveFolderIdentity(connectionId, folder.drive_file_id || folder.id),
    label: folder.name,
    lazy: true,
    provider: 'google_drive',
    relativePath: '',
    role: 'all',
    status: 'connected',
    workspaceRelativePath: displayPath
  };
}

function mergeDriveChildren(node: FolderTreeNode, cache: DriveChildrenCache): FolderTreeNode {
  if (node.provider !== 'google_drive') {
    return { ...node, children: node.children.map((child) => mergeDriveChildren(child, cache)) };
  }
  const cached = cache[node.id];
  const children = (cached?.children || node.children).map((child) => mergeDriveChildren(child, cache));
  const lazy = cached?.loaded
    ? children.length > 0 || Boolean(cached.error)
    : node.lazy || children.length > 0 || Boolean(cached?.error);
  return {
    ...node,
    children,
    error: cached?.error,
    loading: cached?.loading,
    lazy,
  };
}

function sortFolderTree(node: FolderTreeNode) {
  node.children.sort((left, right) => {
    const leftRoleIndex = STORAGE_ROLES.indexOf(left.role as FileRole);
    const rightRoleIndex = STORAGE_ROLES.indexOf(right.role as FileRole);
    if (leftRoleIndex !== rightRoleIndex) {
      return leftRoleIndex - rightRoleIndex;
    }
    return left.label.localeCompare(right.label);
  });
  node.children.forEach(sortFolderTree);
}

function filterFolderTree(node: FolderTreeNode, needle: string): FolderTreeNode | null {
  if (!needle) {
    return node;
  }
  const children = node.children
    .map((child) => filterFolderTree(child, needle))
    .filter((child): child is FolderTreeNode => Boolean(child));
  if (folderNodeMatches(node, needle)) {
    return node;
  }
  if (children.length) {
    return { ...node, children };
  }
  return null;
}

function folderNodeMatches(node: FolderTreeNode, needle: string) {
  return `${node.label} ${node.relativePath} ${node.workspaceRelativePath} ${node.role}`.toLowerCase().includes(needle);
}

function normalizeKind(kind: unknown): PreviewKind | 'all' {
  return typeof kind === 'string' && VIEW_KINDS.has(kind as PreviewKind | 'all') ? kind as PreviewKind | 'all' : 'all';
}

function filterFolderForest(nodes: FolderTreeNode[], needle: string) {
  if (!needle) {
    return nodes;
  }
  return nodes
    .map((node) => filterFolderTree(node, needle))
    .filter((node): node is FolderTreeNode => Boolean(node));
}

function collectDefaultExpandedIds(nodes: FolderTreeNode[], expandAll: boolean) {
  const ids: string[] = [];

  function visit(current: FolderTreeNode) {
    const shouldExpand = expandAll || current.id === STORAGE_ROOT_ID || (current.provider === 'local' && current.relativePath === '');
    if (current.children.length && shouldExpand) {
      ids.push(current.id);
    }
    if (shouldExpand) {
      current.children.forEach(visit);
    }
  }

  nodes.forEach(visit);
  return ids;
}

function folderIdentityFromFilter(filter?: Partial<StorageViewFilter> | null) {
  return folderIdentity(filter?.role || 'all', '');
}

function folderIdentityFromTarget(target: StorageNavigationTarget | null) {
  if (!target) {
    return '';
  }
  if (target.provider === 'google_drive' && target.connectionId) {
    return target.driveFileId
      ? driveFolderIdentity(target.connectionId, target.driveFileId)
      : driveAccountIdentity(target.connectionId);
  }
  if (target.targetType === 'folder' && target.role) {
    return folderIdentity(target.role, target.folderRelativePath || '');
  }
  return folderIdentityFromWorkspacePath(target.workspaceRelativePath);
}

function folderIdentityFromWorkspacePath(workspaceRelativePath: string) {
  const parts = workspaceRelativePath.split('/').filter(Boolean);
  if (parts[0] !== 'storage' || (parts[1] !== 'uploaded' && parts[1] !== 'generated')) {
    return '';
  }
  const pathParts = parts[1] === 'uploaded' && parts.length === 4 && UPLOAD_BUCKET_PATTERN.test(parts[2])
    ? []
    : parts.slice(2, -1);
  return folderIdentity(parts[1], pathParts.join('/'));
}

function openFolderInShell(node: FolderTreeNode, appId: string, ancestors: FolderTreeNode[] = []) {
  const params = node.provider === 'google_drive'
    ? {
      provider: 'google_drive',
      connection_id: node.connectionId,
      ...(node.driveFileId ? { drive_file_id: node.driveFileId } : {}),
      display_path: node.displayPath || node.label,
      ...driveBreadcrumbNavigationParams([...ancestors, node]),
    }
    : {
      folder_relative_path: node.role === 'all' ? '' : node.relativePath,
      role: node.role
    };
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function driveBreadcrumbNavigationParams(nodes: FolderTreeNode[]) {
  const breadcrumbs = driveBreadcrumbTargetsFromNodes(nodes);
  return breadcrumbs.length ? { drive_breadcrumbs: JSON.stringify(breadcrumbs) } : {};
}

function driveBreadcrumbTargetsFromNodes(nodes: FolderTreeNode[]): DriveBreadcrumbTarget[] {
  return nodes
    .map((node) => driveBreadcrumbTargetFromNode(node))
    .filter((node): node is DriveBreadcrumbTarget => Boolean(node));
}

function driveBreadcrumbTargetFromNode(node: FolderTreeNode): DriveBreadcrumbTarget | null {
  if (node.provider !== 'google_drive' || !node.connectionId || !node.driveFileId) {
    return null;
  }
  const displayPath = normalizeDriveBreadcrumbDisplayPath(node.displayPath || node.label);
  if (!displayPath) {
    return null;
  }
  return {
    connectionId: node.connectionId,
    displayPath,
    driveFileId: node.driveFileId,
    label: node.label,
    path: displayPath,
  };
}

function normalizeDriveBreadcrumbDisplayPath(value: string | undefined) {
  const parts = String(value || '').split('/').filter(Boolean);
  if (!parts.length || parts.some((part) => part === '.' || part === '..')) {
    return '';
  }
  return `/${parts.join('/')}`;
}

function KindFilterRail({ activeKind, availableKinds, onSelect }: {
  activeKind: PreviewKind | 'all';
  availableKinds: Set<PreviewKind>;
  onSelect: (kind: PreviewKind | 'all') => void;
}) {
  const dragStateRef = useRef<KindRailDragState | null>(null);
  const suppressClickUntilRef = useRef(0);
  const visibleOptions = useMemo(
    () => KIND_FILTER_OPTIONS.filter((option) => option.kind === 'all' || availableKinds.has(option.kind)),
    [availableKinds]
  );
  const allPreviewFormats = visibleOptions
    .filter((option) => option.kind !== 'all')
    .flatMap((option) => option.formats)
    .slice(0, 3);

  function handlePointerDown(event: PointerEvent<HTMLElement>) {
    if (isMobileLayoutViewport() || event.button !== 0) {
      return;
    }
    const rail = event.currentTarget;
    if (rail.scrollWidth <= rail.clientWidth) {
      return;
    }
    dragStateRef.current = {
      dragged: false,
      pointerId: event.pointerId,
      scrollLeft: rail.scrollLeft,
      startX: event.clientX,
    };
    rail.setPointerCapture(event.pointerId);
    rail.classList.add('is-dragging');
  }

  function handlePointerMove(event: PointerEvent<HTMLElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    const rail = event.currentTarget;
    const deltaX = event.clientX - dragState.startX;
    if (Math.abs(deltaX) > 3) {
      dragState.dragged = true;
    }
    if (!dragState.dragged) {
      return;
    }
    event.preventDefault();
    rail.scrollLeft = dragState.scrollLeft - deltaX;
  }

  function endDrag(event: PointerEvent<HTMLElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    if (dragState.dragged) {
      suppressClickUntilRef.current = Date.now() + 250;
    }
    const rail = event.currentTarget;
    if (rail.hasPointerCapture(event.pointerId)) {
      rail.releasePointerCapture(event.pointerId);
    }
    rail.classList.remove('is-dragging');
    dragStateRef.current = null;
  }

  function handleClickCapture(event: MouseEvent<HTMLElement>) {
    if (Date.now() > suppressClickUntilRef.current) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    suppressClickUntilRef.current = 0;
  }

  return (
    <nav
      aria-label="Filter Storage file types"
      className="storage-kind-rail"
      onClickCapture={handleClickCapture}
      onPointerCancel={endDrag}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
    >
      {visibleOptions.map((option) => {
        const formats = option.kind === 'all' && allPreviewFormats.length
          ? allPreviewFormats
          : option.formats;

        return (
          <button
            aria-label={option.label}
            aria-pressed={activeKind === option.kind}
            className={activeKind === option.kind ? 'storage-kind-button selected' : 'storage-kind-button'}
            key={option.kind}
            onClick={() => onSelect(option.kind)}
            title={option.label}
            type="button"
          >
            <span className="storage-kind-card-slot storage-file-card-scope">
              {formats.length > 1 ? (
                <span className="storage-kind-card-stack">
                  {formats.map((format, index) => (
                    <span className={`storage-kind-stack-item item-${index}`} key={format}>
                      <FileCard formatFile={format} />
                    </span>
                  ))}
                </span>
              ) : (
                <FileCard formatFile={formats[0]} />
              )}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

function StorageSidebarWidget() {
  const storageAppId = useMemo(() => currentStorageAppId(), []);
  const [driveConnections, setDriveConnections] = useState<DriveConnection[]>([]);
  const [driveChildrenCache, setDriveChildrenCache] = useState<DriveChildrenCache>({});
  const [folders, setFolders] = useState<StorageFolder[]>([]);
  const [availableKinds, setAvailableKinds] = useState<Set<PreviewKind>>(() => new Set());
  const [query, setQuery] = useState('');
  const [activeKind, setActiveKind] = useState<PreviewKind | 'all'>('all');
  const [activeViewMode, setActiveViewMode] = useState<StorageViewFilter['mode']>('search');
  const [selectedFolderId, setSelectedFolderId] = useState(STORAGE_ROOT_ID);
  const [dropTarget, setDropTarget] = useState<FolderTreeDropTarget | null>(null);
  const [draggedFolder, setDraggedFolder] = useState<StorageFolder | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [activeOperation, setActiveOperation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const folderTreeNodes = useMemo(() => {
    const storageRoot = buildFolderTree(folders);
    const driveRoots = buildDriveTreeNodes(driveConnections, driveChildrenCache).map((node) => mergeDriveChildren(node, driveChildrenCache));
    return [storageRoot, ...driveRoots];
  }, [driveChildrenCache, driveConnections, folders]);
  const filteredTreeNodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return filterFolderForest(folderTreeNodes, needle);
  }, [folderTreeNodes, query]);
  const defaultExpandedIds = useMemo(() => (
    collectDefaultExpandedIds(filteredTreeNodes, Boolean(query.trim()))
  ), [filteredTreeNodes, query]);
  const treeProviderKey = query.trim().toLowerCase() || 'tree';

  async function refreshCatalog() {
    const payload = await loadCatalog({ limit: 1, offset: 0 });
    setFolders(payload.folders);
    setAvailableKinds(new Set(payload.available_kinds));
    setActiveKind(normalizeKind(payload.state.view_filter.kind));
    setActiveViewMode(payload.state.view_filter.mode);
    setSelectedFolderId((current) => current || folderIdentityFromFilter(payload.state.view_filter));
  }

  async function syncStorageRoot() {
    setActiveOperation('sync:storage');
    try {
      const payload = await loadCatalog({ limit: 1, offset: 0, sync: true });
      setFolders(payload.folders);
      setAvailableKinds(new Set(payload.available_kinds));
      setActiveKind(normalizeKind(payload.state.view_filter.kind));
      setActiveViewMode(payload.state.view_filter.mode);
      setSelectedFolderId((current) => current || folderIdentityFromFilter(payload.state.view_filter));
      setError(null);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : 'Unable to sync Storage.');
    } finally {
      setActiveOperation('');
    }
  }

  async function refreshDriveConnections() {
    const payload = await listDriveConnections();
    setDriveConnections(payload.connections || []);
  }

  async function refreshDriveState() {
    setDriveChildrenCache({});
    await refreshDriveConnections();
  }

  function applyFolderDelta(delta: StorageCatalogDelta) {
    setFolders((current) => applyStorageFoldersDelta(current, delta));
  }

  function revalidateCatalog() {
    refreshCatalog().catch((loadError: Error) => setError(loadError.message));
  }

  async function refreshViewFilter() {
    const payload = (await loadViewFilter()) as ViewFilterPayload;
    const nextFilter = payload.state?.view_filter;
    applyViewFilter(nextFilter);
  }

  function applyViewFilter(nextFilter?: Partial<StorageViewFilter> | null) {
    setQuery(nextFilter?.query || '');
    setActiveKind(normalizeKind(nextFilter?.kind));
    setActiveViewMode(nextFilter?.mode === 'custom' ? 'custom' : 'search');
    setSelectedFolderId(folderIdentityFromFilter(nextFilter));
  }

  async function refreshAll() {
    try {
      await Promise.all([refreshCatalog(), refreshViewFilter(), refreshDriveConnections()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Storage.');
    } finally {
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  function selectKind(kind: PreviewKind | 'all') {
    if (kind === activeKind) {
      return;
    }
    setActiveKind(kind);
    setViewFilter({ kind, preserve_custom: activeViewMode === 'custom' })
      .then((payload) => {
        const nextFilter = payload.state.view_filter;
        applyViewFilter(nextFilter);
        window.parent?.postMessage(storageViewFilterChangedMessage(storageAppId, nextFilter), window.location.origin);
        setError(null);
      })
      .catch((saveError: Error) => {
        setError(saveError.message);
        void refreshViewFilter();
      });
  }

  async function loadDriveChildrenForNode(node: FolderTreeNode, force = false) {
    if (node.provider !== 'google_drive' || !node.lazy || !node.connectionId) {
      return;
    }
    const cached = driveChildrenCache[node.id];
    if (!force && (cached?.loaded || cached?.loading || node.status === 'reconnect_required')) {
      return;
    }
    setDriveChildrenCache((current) => ({
      ...current,
      [node.id]: { ...(current[node.id] || { children: [] }), loading: true }
    }));
    try {
      const payload = node.driveFileId
        ? await listDriveChildren(node.connectionId, node.driveFileId, { limit: DRIVE_PAGE_LIMIT })
        : await listDriveRoots(node.connectionId, { limit: DRIVE_PAGE_LIMIT });
      const children = (payload.folders || []).map((folder) => driveFolderNode(node.connectionId || payload.connection_id, folder, node.displayPath));
      setDriveChildrenCache((current) => ({
        ...current,
        [node.id]: { children, loaded: true }
      }));
      setError(null);
    } catch (loadError) {
      setDriveChildrenCache((current) => ({
        ...current,
        [node.id]: {
          ...(current[node.id] || { children: [] }),
          error: loadError instanceof Error ? loadError.message : 'Unable to load Google Drive folders.',
          loaded: false,
          loading: false
        }
      }));
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Google Drive folders.');
    }
  }

  async function ensureDriveChildren(node: FolderTreeNode) {
    await loadDriveChildrenForNode(node);
  }

  async function syncDriveAccount(node: FolderTreeNode) {
    if (!node.connectionId || node.status !== 'connected') {
      setError(node.connectionId ? 'Reconnect required' : 'Google Drive connection is missing.');
      return;
    }
    setActiveOperation(`sync:${node.connectionId}`);
    try {
      await syncDriveConnection(node.connectionId);
      setDriveChildrenCache((current) => {
        const next = { ...current };
        const cachePrefix = `${driveAccountIdentity(node.connectionId!)}:`;
        Object.keys(next).forEach((key) => {
          if (key === node.id || key.startsWith(cachePrefix)) {
            delete next[key];
          }
        });
        return next;
      });
      await refreshDriveConnections();
      await loadDriveChildrenForNode(node, true);
      setError(null);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : 'Unable to sync Google Drive.');
    } finally {
      setActiveOperation('');
    }
  }

  async function disconnectDriveAccount(node: FolderTreeNode) {
    if (!node.connectionId) {
      setError('Google Drive connection is missing.');
      return;
    }
    if (node.status === 'disconnected') {
      setError('Google Drive account is already disconnected.');
      return;
    }
    setActiveOperation(`disconnect:${node.connectionId}`);
    try {
      await disconnectDriveConnection(node.connectionId);
      setDriveChildrenCache((current) => {
        const next = { ...current };
        const cachePrefix = `${driveAccountIdentity(node.connectionId!)}:`;
        Object.keys(next).forEach((key) => {
          if (key === node.id || key.startsWith(cachePrefix)) {
            delete next[key];
          }
        });
        return next;
      });
      await refreshDriveConnections();
      setError(null);
    } catch (disconnectError) {
      setError(disconnectError instanceof Error ? disconnectError.message : 'Unable to disconnect Google Drive.');
    } finally {
      setActiveOperation('');
    }
  }

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        context?: Record<string, unknown>;
        owner_app_id?: string;
        resource?: string;
        type?: string;
      } & ActiveStorageSelectionMessage;
      const contextTarget = storageTargetFromWidgetContext(payload);
      if (contextTarget) {
        const folderId = folderIdentityFromTarget(contextTarget);
        if (folderId) setSelectedFolderId(folderId);
        return;
      }
      const activeTarget = storageSelectionFromMessage(payload);
      if (activeTarget) {
        const folderId = folderIdentityFromTarget(activeTarget);
        if (folderId) setSelectedFolderId(folderId);
        return;
      }
      if (payload.type !== 'maverick.widget.data-changed' || payload.owner_app_id !== storageAppId) {
        return;
      }
      if (payload.resource === 'files') {
        void refreshCatalog();
        setDriveChildrenCache({});
      }
      if (payload.resource === 'drive-connections') {
        void refreshDriveState();
      }
      if (payload.resource === 'view-state') {
        const nextFilter = storageViewFilterFromMessage(payload, storageAppId);
        if (nextFilter) {
          applyViewFilter(nextFilter);
          return;
        }
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [storageAppId]);

  function selectFolder(node: FolderTreeNode, ancestors: FolderTreeNode[] = []) {
    setSelectedFolderId(node.id);
    if (node.provider === 'google_drive' && node.status === 'reconnect_required') {
      setError('Reconnect required');
      return;
    }
    openFolderInShell(node, storageAppId, ancestors);
  }

  function handleFolderDragStart(event: DragEvent<HTMLElement>, node: FolderTreeNode) {
    if (node.provider !== 'local') {
      event.preventDefault();
      return;
    }
    const folder = storageFolderFromNode(node);
    if (!folder) {
      event.preventDefault();
      return;
    }
    attachStorageFolderDragImage(event);
    writeStorageFolderDragData(event.dataTransfer, storageDragPayloadFromFolder(folder, storageAppId));
    setDraggedFolder(folder);
  }

  function handleFolderDrag(event: DragEvent<HTMLElement>, node: FolderTreeNode) {
    if (node.provider !== 'local') {
      return;
    }
    let status = storageMoveDropStatus(event.dataTransfer, node.role);
    if (status === 'none') {
      return;
    }
    const sourceSelection = readStorageSelectionDragData(event.dataTransfer, storageAppId);
    if (status === 'ready' && sourceSelection && storageSelectionMoveTargetBlocked(sourceSelection, node)) {
      status = 'blocked';
    }
    if (status === 'ready' && draggedFolder && folderMoveTargetBlocked(draggedFolder, node)) {
      status = 'blocked';
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = status === 'ready' ? 'move' : 'none';
    setDropTarget({ nodeId: node.id, status });
  }

  function handleFolderDragLeave(event: DragEvent<HTMLElement>, node: FolderTreeNode) {
    if (node.provider !== 'local') {
      return;
    }
    if (storageMoveDropStatus(event.dataTransfer, node.role) === 'none') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropTarget((current) => current?.nodeId === node.id ? null : current);
  }

  async function handleFolderDrop(event: DragEvent<HTMLElement>, node: FolderTreeNode) {
    if (node.provider !== 'local') {
      return;
    }
    const status = storageMoveDropStatus(event.dataTransfer, node.role);
    if (status === 'none') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropTarget(null);
    if (node.role === 'all') {
      setError('Choose Uploaded or Generated before moving Storage items.');
      setDraggedFolder(null);
      return;
    }
    const sourceSelection = readStorageSelectionDragData(event.dataTransfer, storageAppId);
    if (sourceSelection) {
      if (storageSelectionMoveTargetBlocked(sourceSelection, node)) {
        setError('Selected items can only be moved within their current storage section, and folders cannot move into themselves or child folders.');
        setDraggedFolder(null);
        return;
      }
      const movePlan = storageSelectionMovePlan(sourceSelection);
      try {
        const payload = await moveItemsReferences(movePlan.files, movePlan.folders, node.role, node.relativePath);
        for (const movedFolder of payload.folders) {
          applyFolderDelta({ type: 'move_folder', previous: movedFolder.previous, folder: movedFolder.folder });
        }
        revalidateCatalog();
        setError(null);
      } catch (moveError) {
        setError(moveError instanceof Error ? moveError.message : 'Unable to move selected items.');
      } finally {
        setDraggedFolder(null);
      }
      return;
    }
    const sourceFile = readStorageFileDragData(event.dataTransfer, storageAppId);
    if (sourceFile) {
      if (sourceFile.role !== node.role) {
        setError('Files can only be moved within their current storage section.');
        setDraggedFolder(null);
        return;
      }
      try {
        await moveFileReference(sourceFile, node.relativePath);
        revalidateCatalog();
        setError(null);
      } catch (moveError) {
        setError(moveError instanceof Error ? moveError.message : 'Unable to move file.');
      } finally {
        setDraggedFolder(null);
      }
      return;
    }

    const sourceFolder = readStorageFolderDragData(event.dataTransfer, storageAppId) || draggedFolder;
    if (!sourceFolder) {
      setError('This Storage item drag could not be read.');
      setDraggedFolder(null);
      return;
    }
    if (sourceFolder.role !== node.role) {
      setError('Folders can only be moved within their current storage section.');
      setDraggedFolder(null);
      return;
    }
    if (folderMoveTargetBlocked(sourceFolder, node)) {
      setError('Folders cannot be moved into themselves or one of their child folders.');
      setDraggedFolder(null);
      return;
    }
    try {
      const payload = await moveFolderReference(sourceFolder, node.relativePath);
      applyFolderDelta({ type: 'move_folder', previous: sourceFolder, folder: payload.folder });
      revalidateCatalog();
      setError(null);
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : 'Unable to move folder.');
    } finally {
      setDraggedFolder(null);
    }
  }

  return (
    <main className={`storage-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      {isInitialLoading ? (
        <KindFilterRailSkeleton />
      ) : (
        <KindFilterRail activeKind={activeKind} availableKinds={availableKinds} onSelect={selectKind} />
      )}

      {error ? <p className="storage-sidebar-empty">{error}</p> : null}

      <div className="storage-sidebar-list storage-sidebar-tree-list">
        {isInitialLoading ? (
          <StorageSidebarSkeleton />
        ) : filteredTreeNodes.length ? (
          <TreeProvider
            animateExpand
            className="storage-folder-tree"
            defaultExpandedIds={defaultExpandedIds}
            indent={18}
            key={treeProviderKey}
            onSelectionChange={(ids) => setSelectedFolderId(ids[ids.length - 1] || '')}
            selectedIds={selectedFolderId ? [selectedFolderId] : []}
          >
            <TreeView>
              {filteredTreeNodes.map((node, index) => (
                <FolderTreeNodeView
                  ancestors={[]}
                  dropTarget={dropTarget}
                  isLast={index === filteredTreeNodes.length - 1}
                  key={node.id}
                  level={0}
                  node={node}
                  onDragEnd={() => setDraggedFolder(null)}
                  onDragLeave={handleFolderDragLeave}
                  onDragOver={handleFolderDrag}
                  onDragStart={handleFolderDragStart}
                  onDrop={handleFolderDrop}
                  onEnsureChildren={ensureDriveChildren}
                  onDisconnectDriveAccount={disconnectDriveAccount}
                  onSelect={selectFolder}
                  onSyncDriveAccount={syncDriveAccount}
                  onSyncStorageRoot={syncStorageRoot}
                  activeOperation={activeOperation}
                />
              ))}
            </TreeView>
          </TreeProvider>
        ) : (
          <p className="storage-sidebar-empty">No folders found.</p>
        )}
      </div>

    </main>
  );
}

function FolderTreeNodeView({ activeOperation, ancestors, dropTarget, node, level, isLast, onDragEnd, onDragLeave, onDragOver, onDragStart, onDrop, onDisconnectDriveAccount, onEnsureChildren, onSelect, onSyncDriveAccount, onSyncStorageRoot }: {
  activeOperation: string;
  ancestors: FolderTreeNode[];
  dropTarget: FolderTreeDropTarget | null;
  isLast: boolean;
  level: number;
  node: FolderTreeNode;
  onDragEnd: () => void;
  onDragLeave: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDragOver: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDragStart: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDrop: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDisconnectDriveAccount: (node: FolderTreeNode) => Promise<void>;
  onEnsureChildren: (node: FolderTreeNode) => void;
  onSelect: (node: FolderTreeNode, ancestors: FolderTreeNode[]) => void;
  onSyncDriveAccount: (node: FolderTreeNode) => Promise<void>;
  onSyncStorageRoot: () => Promise<void>;
}) {
  const hasChildren = node.children.length > 0 || Boolean(node.lazy);
  const nodeDropStatus = dropTarget?.nodeId === node.id ? dropTarget.status : null;
  const isStorageRoot = node.id === STORAGE_ROOT_ID;
  const isDriveAccount = isDriveAccountNode(node);
  const isDriveConnected = isDriveAccount && node.status === 'connected';
  const isDriveDisconnected = isDriveAccount && node.status === 'disconnected';
  const isSyncing = activeOperation === `sync:${isDriveAccount ? node.connectionId : 'storage'}`;
  const isDisconnecting = activeOperation === `disconnect:${node.connectionId}`;
  const label = node.status === 'reconnect_required' ? `${node.label} (Reconnect required)` : node.label;
  const childAncestors = [...ancestors, node];

  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        className={nodeDropStatus === 'ready' ? 'storage-folder-tree-drop-ready' : nodeDropStatus === 'blocked' ? 'storage-folder-tree-drop-blocked' : ''}
        onClick={() => onSelect(node, ancestors)}
        toggleOnTriggerClick={false}
        draggable={node.provider === 'local' && node.role !== 'all' && Boolean(node.relativePath)}
        onDragEnd={onDragEnd}
        onDragEnter={(event) => onDragOver(event, node)}
        onDragLeave={(event) => onDragLeave(event, node)}
        onDragOver={(event) => onDragOver(event, node)}
        onDragStartCapture={(event) => onDragStart(event, node)}
        onDrop={(event) => onDrop(event, node)}
      >
        <TreeExpander hasChildren={hasChildren} onClick={() => onEnsureChildren(node)} />
        <TreeIcon
          className="storage-folder-drag-icon-source"
          hasChildren={true}
          icon={folderTreeIcon(node)}
        />
        <TreeLabel title={node.error || node.workspaceRelativePath}>{node.loading ? `${label}...` : label}</TreeLabel>
        {isStorageRoot || isDriveAccount ? (
          <span className="storage-folder-tree-actions">
            <button
              aria-label={`Sync ${node.label}`}
              className="storage-folder-tree-sync"
              disabled={Boolean(activeOperation) || (isDriveAccount && !isDriveConnected)}
              onClick={(event) => {
                event.stopPropagation();
                void (isDriveAccount ? onSyncDriveAccount(node) : onSyncStorageRoot());
              }}
              title={`Sync ${node.label}`}
              type="button"
            >
              <RefreshCw className={isSyncing ? 'is-spinning' : ''} aria-hidden="true" />
            </button>
            {isDriveAccount ? (
              <button
                aria-label={`Disconnect ${node.label}`}
                className="storage-folder-tree-sync storage-folder-tree-disconnect"
                disabled={Boolean(activeOperation) || isDriveDisconnected}
                onClick={(event) => {
                  event.stopPropagation();
                  void onDisconnectDriveAccount(node);
                }}
                title={`Disconnect ${node.label}`}
                type="button"
              >
                <LogOut className={isDisconnecting ? 'is-breathing' : ''} aria-hidden="true" />
              </button>
            ) : null}
          </span>
        ) : null}
      </TreeNodeTrigger>
      <TreeNodeContent hasChildren={hasChildren}>
        {node.error ? (
          <TreeNode isLast level={level + 1} nodeId={`${node.id}:error`}>
            <TreeNodeTrigger className="storage-folder-tree-status" toggleOnTriggerClick={false}>
              <TreeExpander hasChildren={false} />
              <TreeIcon hasChildren={false} />
              <TreeLabel title={node.error}>{node.error}</TreeLabel>
            </TreeNodeTrigger>
          </TreeNode>
        ) : null}
        {node.children.map((child, index) => (
          <FolderTreeNodeView
            ancestors={childAncestors}
            dropTarget={dropTarget}
            isLast={index === node.children.length - 1}
            key={child.id}
            level={level + 1}
            node={child}
            onDragEnd={onDragEnd}
            onDragLeave={onDragLeave}
            onDragOver={onDragOver}
            onDragStart={onDragStart}
            onDrop={onDrop}
            onDisconnectDriveAccount={onDisconnectDriveAccount}
            onEnsureChildren={onEnsureChildren}
            onSelect={onSelect}
            onSyncDriveAccount={onSyncDriveAccount}
            onSyncStorageRoot={onSyncStorageRoot}
            activeOperation={activeOperation}
          />
        ))}
      </TreeNodeContent>
    </TreeNode>
  );
}

function KindFilterRailSkeleton() {
  return (
    <nav aria-hidden="true" className="storage-kind-rail storage-kind-rail-skeleton">
      {Array.from({ length: 5 }).map((_, index) => (
        <span className="storage-kind-button storage-kind-button-skeleton" key={index}>
          <span className="storage-kind-card-slot">
            <span />
          </span>
        </span>
      ))}
    </nav>
  );
}

function StorageSidebarSkeleton() {
  return (
    <div className="storage-sidebar-skeleton" role="status" aria-label="Storage folders are loading">
      {Array.from({ length: 7 }).map((_, index) => (
        <div className={`storage-sidebar-skeleton__row depth-${Math.min(index, 3)}`} key={index} aria-hidden="true">
          <span className="storage-sidebar-skeleton__expander" />
          <span className="storage-sidebar-skeleton__icon" />
          <span className="storage-sidebar-skeleton__copy">
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('storage-sidebar-root') as HTMLElement).render(<StorageSidebarWidget />);
