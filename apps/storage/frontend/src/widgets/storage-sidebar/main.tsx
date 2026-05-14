import { useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent, type PointerEvent } from 'react';
import { createRoot } from 'react-dom/client';
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
import { currentStorageAppId, loadCatalog, loadViewFilter, moveFileReference, moveFolderReference, moveItemsReferences, setViewFilter } from '../../storageApi';
import { kindLabels, roleLabels } from '../../storageMeta';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { storageSelectionFromMessage, type ActiveStorageSelectionMessage } from '../../lib/activeStorageSelection';
import { applyStorageFoldersDelta, type StorageCatalogDelta } from '../../lib/storageCatalogDelta';
import { attachStorageFolderDragImage } from '../../lib/storageDragImage';
import { readStorageFileDragData, readStorageFolderDragData, readStorageSelectionDragData, storageDragPayloadFromFolder, storageMoveDropStatus, writeStorageFolderDragData, type StorageMoveDropStatus, type StorageSelectionDragPayload } from '../../lib/storageDragDrop';
import { storageTargetFromWidgetContext, type StorageNavigationTarget } from '../../lib/storageNavigationParams';
import { storageViewFilterChangedMessage, storageViewFilterFromMessage } from '../../lib/storageViewFilterEvents';
import type { FileRole, StorageFolder, StorageViewFilter, PreviewKind } from '../../types';
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
  id: string;
  label: string;
  relativePath: string;
  role: StorageTreeRole;
  workspaceRelativePath: string;
};

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

function normalizeFolderPath(path: string) {
  return path.split('/').filter(Boolean).join('/');
}

function folderMoveTargetBlocked(source: Pick<StorageFolder, 'relative_path' | 'role'>, target: FolderTreeNode) {
  if (target.role === 'all' || source.role !== target.role) {
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
  if (node.role === 'all' || !node.relativePath) {
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
    relativePath: '',
    role: 'uploaded',
    workspaceRelativePath: 'storage/uploaded'
  };
  const generatedRoot: FolderTreeNode = {
    children: [],
    id: folderIdentity('generated', ''),
    label: roleLabels.generated,
    relativePath: '',
    role: 'generated',
    workspaceRelativePath: 'storage/generated'
  };
  const root: FolderTreeNode = {
    children: [uploadedRoot, generatedRoot],
    id: STORAGE_ROOT_ID,
    label: 'Storage',
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

function collectDefaultExpandedIds(node: FolderTreeNode, expandAll: boolean) {
  const ids: string[] = [];

  function visit(current: FolderTreeNode) {
    const shouldExpand = expandAll || current.id === STORAGE_ROOT_ID || current.relativePath === '';
    if (current.children.length && shouldExpand) {
      ids.push(current.id);
    }
    if (shouldExpand) {
      current.children.forEach(visit);
    }
  }

  visit(node);
  return ids;
}

function folderIdentityFromFilter(filter?: Partial<StorageViewFilter> | null) {
  return folderIdentity(filter?.role || 'all', '');
}

function folderIdentityFromTarget(target: StorageNavigationTarget | null) {
  if (!target) {
    return '';
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

function openFolderInShell(node: FolderTreeNode, appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        folder_relative_path: node.role === 'all' ? '' : node.relativePath,
        role: node.role
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
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
  const [folders, setFolders] = useState<StorageFolder[]>([]);
  const [availableKinds, setAvailableKinds] = useState<Set<PreviewKind>>(() => new Set());
  const [query, setQuery] = useState('');
  const [activeKind, setActiveKind] = useState<PreviewKind | 'all'>('all');
  const [activeViewMode, setActiveViewMode] = useState<StorageViewFilter['mode']>('search');
  const [selectedFolderId, setSelectedFolderId] = useState(STORAGE_ROOT_ID);
  const [dropTarget, setDropTarget] = useState<FolderTreeDropTarget | null>(null);
  const [draggedFolder, setDraggedFolder] = useState<StorageFolder | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const folderTreeRoot = useMemo(() => buildFolderTree(folders), [folders]);
  const filteredTreeRoot = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return filterFolderTree(folderTreeRoot, needle);
  }, [folderTreeRoot, query]);
  const defaultExpandedIds = useMemo(() => (
    filteredTreeRoot ? collectDefaultExpandedIds(filteredTreeRoot, Boolean(query.trim())) : []
  ), [filteredTreeRoot, query]);
  const treeProviderKey = `${query.trim().toLowerCase() || 'tree'}:${folders.length}`;

  async function refreshCatalog() {
    const payload = await loadCatalog({ limit: 1, offset: 0 });
    setFolders(payload.folders);
    setAvailableKinds(new Set(payload.available_kinds));
    setActiveKind(normalizeKind(payload.state.view_filter.kind));
    setActiveViewMode(payload.state.view_filter.mode);
    setSelectedFolderId((current) => current || folderIdentityFromFilter(payload.state.view_filter));
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
      await Promise.all([refreshCatalog(), refreshViewFilter()]);
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

  function selectFolder(node: FolderTreeNode) {
    setSelectedFolderId(node.id);
    openFolderInShell(node, storageAppId);
  }

  function handleFolderDragStart(event: DragEvent<HTMLElement>, node: FolderTreeNode) {
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
    if (storageMoveDropStatus(event.dataTransfer, node.role) === 'none') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropTarget((current) => current?.nodeId === node.id ? null : current);
  }

  async function handleFolderDrop(event: DragEvent<HTMLElement>, node: FolderTreeNode) {
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
        ) : filteredTreeRoot ? (
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
              <FolderTreeNodeView
                dropTarget={dropTarget}
                isLast
                level={0}
                node={filteredTreeRoot}
                onDragEnd={() => setDraggedFolder(null)}
                onDragLeave={handleFolderDragLeave}
                onDragOver={handleFolderDrag}
                onDragStart={handleFolderDragStart}
                onDrop={handleFolderDrop}
                onSelect={selectFolder}
              />
            </TreeView>
          </TreeProvider>
        ) : (
          <p className="storage-sidebar-empty">No folders found.</p>
        )}
      </div>

    </main>
  );
}

function FolderTreeNodeView({ dropTarget, node, level, isLast, onDragEnd, onDragLeave, onDragOver, onDragStart, onDrop, onSelect }: {
  dropTarget: FolderTreeDropTarget | null;
  isLast: boolean;
  level: number;
  node: FolderTreeNode;
  onDragEnd: () => void;
  onDragLeave: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDragOver: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDragStart: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onDrop: (event: DragEvent<HTMLElement>, node: FolderTreeNode) => void;
  onSelect: (node: FolderTreeNode) => void;
}) {
  const hasChildren = node.children.length > 0;
  const nodeDropStatus = dropTarget?.nodeId === node.id ? dropTarget.status : null;

  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        className={nodeDropStatus === 'ready' ? 'storage-folder-tree-drop-ready' : nodeDropStatus === 'blocked' ? 'storage-folder-tree-drop-blocked' : ''}
        onClick={() => onSelect(node)}
        draggable={node.role !== 'all' && Boolean(node.relativePath)}
        onDragEnd={onDragEnd}
        onDragEnter={(event) => onDragOver(event, node)}
        onDragLeave={(event) => onDragLeave(event, node)}
        onDragOver={(event) => onDragOver(event, node)}
        onDragStartCapture={(event) => onDragStart(event, node)}
        onDrop={(event) => onDrop(event, node)}
      >
        <TreeExpander hasChildren={hasChildren} />
        <TreeIcon className="storage-folder-drag-icon-source" hasChildren />
        <TreeLabel title={node.workspaceRelativePath}>{node.label}</TreeLabel>
      </TreeNodeTrigger>
      <TreeNodeContent hasChildren={hasChildren}>
        {node.children.map((child, index) => (
          <FolderTreeNodeView
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
            onSelect={onSelect}
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
