import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, DragEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { Home } from 'lucide-react';
import { AnimatedFileCollection, CollectionViewToggle, type CollectionViewMode } from './components/ui/animated-collection';
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from './components/ui/breadcramb';
import { CATALOG_PAGE_LIMIT, clearCustomView, completeDriveOAuth, currentStorageAppId, decodeBase64, deleteFile, deleteFolder, downloadFolder, listDriveChildren, listDriveRoots, loadCatalog, loadViewFilter, moveFileReference, moveFolderReference, moveItemsReferences, readDriveFile, readFile, renameDriveFile, renameFile, setViewFilter, trashDriveFile, updateMarkdownFile, uploadFile } from './storageApi';
import { canInlinePreview, canTextPreview, StoragePreview } from './filePreview';
import { formatBytes, formatMegabytes, kindLabels, roleLabels } from './storageMeta';
import { Icon } from './Icon';
import { useLongPressSelection } from './hooks/useLongPressSelection';
import { notifyActiveStorageFolderSelection, notifyActiveStorageSelection } from './lib/activeStorageSelection';
import { breadcrumbRefreshPlan, catalogBrowserDisplayState, catalogLoadedCountAfterPage, catalogLoadedCountAfterRefresh, folderOpenRefreshPlan, missingNavigationTargetPlan, resolvedFileNavigationPlan } from './lib/storageCatalogFlow';
import { applyStorageFilesDelta, applyStorageFoldersDelta, type StorageCatalogDelta } from './lib/storageCatalogDelta';
import { fileFolderSelection, folderParentPath, folderStatsForSelection, normalizeFolderPath } from './lib/storageFolderLayer';
import { attachStorageFolderDragImage } from './lib/storageDragImage';
import { readStorageFileDragData, readStorageFolderDragData, readStorageSelectionDragData, storageDragPayloadFromFile, storageDragPayloadFromFolder, storageDragPayloadFromSelection, storageMoveDropStatus, writeStorageFileDragData, writeStorageFolderDragData, writeStorageSelectionDragData, type StorageFileDragPayload, type StorageMoveDropStatus, type StorageSelectionDragPayload } from './lib/storageDragDrop';
import { canRequestFullscreen, elementIsFullscreen, exitDocumentFullscreen, requestElementFullscreen } from './lib/browserFullscreen';
import { folderTargetFromMissingFileTarget, storageTargetFromParams, type StorageNavigationParams, type StorageNavigationTarget } from './lib/storageNavigationParams';
import { storageOAuthCallbackFromLocation, type StorageOAuthCallback } from './lib/storageOAuthRuntime';
import { storageCustomScopedFiles, storageViewVisibleFiles, storageViewVisibleFolders } from './lib/storageSearch';
import { storageViewFilterFromMessage } from './lib/storageViewFilterEvents';
import { loadFullPreview } from './previewCache';
import type { CatalogPayload, FileRole, StorageFile, StorageFolder, StorageViewFilter, PreviewKind, PreviewTablePayload } from './types';
import './styles/main.css';

const DOWNLOAD_BYTES = 100 * 1024 * 1024;
const VIEW_SYNC_MS = 2000;
const LAYOUT_STORAGE_KEY = 'storage.layout-mode';
const PREVIEW_VIEWPORT_GAP = 44;
const PREVIEW_IMAGE_MAX_WIDTH = 1040;
const PREVIEW_IMAGE_MIN_SIZE = 120;

type DropFeedback = 'idle' | 'ready' | 'blocked' | 'uploading' | 'success' | 'error';
type PreviewFullscreenMode = 'none' | 'native' | 'expanded';
type PendingDelete =
  | { kind: 'file'; file: StorageFile }
  | { kind: 'folder'; folder: StorageFolder };
type DraggingSelectionState = {
  fileIds: Set<string>;
  folderIds: Set<string>;
};
type CatalogRefreshLoading = 'foreground' | 'background';
type CatalogRequestOptions = {
  fileIds?: string[];
  folderPath?: string;
  viewMode?: StorageViewFilter['mode'];
  workspacePaths?: string[];
};
type CatalogRefreshOptions = CatalogRequestOptions & {
  loading?: CatalogRefreshLoading;
};
type DriveFolderTarget = {
  connectionId: string;
  displayPath: string;
  driveFileId: string;
};

const viewKinds = new Set<PreviewKind | 'all'>(['all', 'image', 'video', 'audio', 'pdf', 'document', 'presentation', 'spreadsheet', 'markdown', 'text', 'file']);
const storageRootRoles: FileRole[] = ['uploaded', 'generated'];
const emptyIdSet = new Set<string>();

type PreviewImageSize = {
  width: number;
  height: number;
};

type PreviewImageStyle = CSSProperties & {
  '--preview-image-height'?: string;
};

function normalizedViewFilter(filter?: Partial<StorageViewFilter>): StorageViewFilter {
  const role = filter?.role === 'generated' || filter?.role === 'uploaded' ? filter.role : 'all';
  const kind = filter?.kind && viewKinds.has(filter.kind) ? filter.kind : 'all';
  const mode = filter?.mode === 'custom' ? 'custom' : 'search';
  return {
    mode,
    title: filter?.title || '',
    query: filter?.query || '',
    role,
    kind,
    file_ids: Array.isArray(filter?.file_ids) ? filter.file_ids : [],
    workspace_relative_paths: Array.isArray(filter?.workspace_relative_paths) ? filter.workspace_relative_paths : [],
    updated_at: filter?.updated_at || ''
  };
}

function folderBreadcrumbItems(currentFolderPath: string) {
  const parts = currentFolderPath.split('/').filter(Boolean);
  return parts.map((part, index) => ({
    label: part,
    path: parts.slice(0, index + 1).join('/')
  }));
}

function storageRootFolder(role: FileRole): StorageFolder {
  return {
    id: `${role}:/`,
    role,
    name: roleLabels[role],
    relative_path: '',
    workspace_relative_path: `storage/${role}`,
    modified_at: ''
  };
}

function isFileRole(role: unknown): role is FileRole {
  return role === 'uploaded' || role === 'generated';
}

function isDriveItem(item: Pick<StorageFile | StorageFolder, 'provider'>) {
  return item.provider === 'google_drive';
}

function itemCan(item: Pick<StorageFile | StorageFolder, 'capabilities'>, capability: keyof NonNullable<StorageFile['capabilities']>, fallback = true) {
  return item.capabilities ? Boolean(item.capabilities[capability]) : fallback;
}

function driveItemPath(item: Pick<StorageFile | StorageFolder, 'display_path' | 'name'>) {
  return item.display_path || item.name;
}

function folderContainsPath(folder: Pick<StorageFolder, 'relative_path'>, relativePath: string) {
  const folderPath = normalizeFolderPath(folder.relative_path);
  const childPath = normalizeFolderPath(relativePath);
  return !folderPath || childPath === folderPath || childPath.startsWith(`${folderPath}/`);
}

function fileMatchesReference(file: StorageFile | null | undefined, reference: Pick<StorageFile, 'role' | 'relative_path'> & Partial<Pick<StorageFile, 'id' | 'file_id' | 'workspace_relative_path'>>) {
  return Boolean(file && (
    (reference.id && file.id === reference.id)
    || (reference.file_id && file.file_id === reference.file_id)
    || (reference.workspace_relative_path && file.workspace_relative_path === reference.workspace_relative_path)
    || (file.role === reference.role && file.relative_path === reference.relative_path)
  ));
}

function fileMatchesDragPayload(file: StorageFile | null | undefined, payload: Pick<StorageFileDragPayload, 'file_id' | 'relative_path' | 'role' | 'workspace_relative_path'>) {
  return fileMatchesReference(file, {
    file_id: payload.file_id,
    relative_path: payload.relative_path,
    role: payload.role,
    workspace_relative_path: payload.workspace_relative_path,
  });
}

function folderMoveTargetBlocked(source: Pick<StorageFolder, 'relative_path' | 'role'>, targetRole: FileRole, targetFolderPath: string) {
  if (source.role !== targetRole) {
    return true;
  }
  const sourcePath = normalizeFolderPath(source.relative_path);
  const targetPath = normalizeFolderPath(targetFolderPath);
  if (!sourcePath) {
    return true;
  }
  return targetPath === sourcePath || targetPath.startsWith(`${sourcePath}/`);
}

function storageSelectionMoveTargetBlocked(selection: StorageSelectionDragPayload, targetRole: FileRole, targetFolderPath: string) {
  return selection.files.some((file) => file.role !== targetRole)
    || selection.folders.some((folder) => folder.role !== targetRole || folderMoveTargetBlocked(folder, targetRole, targetFolderPath));
}

function storageSelectionItemCount(selection: Pick<StorageSelectionDragPayload, 'files' | 'folders'>) {
  return selection.files.length + selection.folders.length;
}

function storageSelectionMovePlan(files: StorageFile[], folders: StorageFolder[]) {
  const movableFolders = folders
    .filter((folder) => Boolean(folder.relative_path))
    .filter((folder) => !folders.some((parent) => (
      parent.id !== folder.id
      && parent.role === folder.role
      && Boolean(parent.relative_path)
      && folderContainsPath(parent, folder.relative_path)
    )));
  const movableFiles = files.filter((file) => !movableFolders.some((folder) => folder.role === file.role && folderContainsPath(folder, file.relative_path)));
  return { files: movableFiles, folders: movableFolders };
}

function storageDragSelectionMovePlan(selection: StorageSelectionDragPayload) {
  const movableFolders = selection.folders.filter((folder) => !selection.folders.some((parent) => (
    parent.folder_id !== folder.folder_id
    && parent.role === folder.role
    && folderContainsPath(parent, folder.relative_path)
  )));
  const movableFiles = selection.files.filter((file) => !movableFolders.some((folder) => folder.role === file.role && folderContainsPath(folder, file.relative_path)));
  return { files: movableFiles, folders: movableFolders };
}

function pruneSelection(current: Set<string>, visibleIds: Set<string>) {
  let changed = false;
  const next = new Set<string>();
  current.forEach((id) => {
    if (visibleIds.has(id)) {
      next.add(id);
    } else {
      changed = true;
    }
  });
  return changed ? next : current;
}

function pathAfterFolderMove(path: string, sourceFolderPath: string, movedFolderPath: string) {
  const normalizedPath = normalizeFolderPath(path);
  const normalizedSource = normalizeFolderPath(sourceFolderPath);
  const normalizedTarget = normalizeFolderPath(movedFolderPath);
  if (!normalizedSource) {
    return normalizedPath;
  }
  if (normalizedPath === normalizedSource) {
    return normalizedTarget;
  }
  if (normalizedPath.startsWith(`${normalizedSource}/`)) {
    const suffix = normalizedPath.slice(normalizedSource.length + 1);
    return normalizedTarget ? `${normalizedTarget}/${suffix}` : suffix;
  }
  return normalizedPath;
}

function initialLayoutMode(): CollectionViewMode {
  const storedMode = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  return storedMode === 'card' || storedMode === 'cards' ? 'card' : 'list';
}

function fileFromNavigationTarget(files: StorageFile[], target: StorageNavigationTarget | null) {
  if (!target) return null;
  return files.find((file) => {
    if (target.fileId && (file.id === target.fileId || file.file_id === target.fileId || file.path_id === target.fileId)) return true;
    return Boolean(target.workspaceRelativePath && file.workspace_relative_path === target.workspaceRelativePath);
  }) || null;
}

function mergeUniqueFiles(current: StorageFile[], incoming: StorageFile[]) {
  const byId = new Map(current.map((file) => [file.id, file]));
  incoming.forEach((file) => byId.set(file.id, file));
  return Array.from(byId.values());
}

function driveLoadedItemCount(files: StorageFile[], folders: StorageFolder[]) {
  return files.length + folders.length;
}

function hasDraggedFiles(dataTransfer: DataTransfer) {
  if (Array.from(dataTransfer.types || []).includes('Files')) return true;
  return Array.from(dataTransfer.items || []).some((item) => item.kind === 'file');
}

function fittedPreviewImageSize(image: PreviewImageSize, viewport: PreviewImageSize, headerHeight: number) {
  const maxWidth = Math.max(PREVIEW_IMAGE_MIN_SIZE, Math.min(PREVIEW_IMAGE_MAX_WIDTH, viewport.width - PREVIEW_VIEWPORT_GAP));
  const maxHeight = Math.max(PREVIEW_IMAGE_MIN_SIZE, viewport.height - PREVIEW_VIEWPORT_GAP - headerHeight);
  const scale = Math.min(maxWidth / image.width, maxHeight / image.height);
  if (!Number.isFinite(scale) || scale <= 0) return null;
  return {
    width: Math.max(1, Math.round(image.width * scale)),
    height: Math.max(1, Math.round(image.height * scale))
  };
}

function uploadTargetLabel(role: FileRole | 'all', folderPath: string) {
  if (role === 'all') return 'Choose Generated or Uploaded first';
  return `${roleLabels[role]}${folderPath ? ` / ${folderPath}` : ''}`;
}

function FolderCard({ canDelete, canDownload, dragging, folder, onDelete, onDownload, onDragEnd, onDragStart, onDropStatus, onDropStorageItem, onLongPress, onOpen, onShowDetails, onToggleSelection, selected, selectionMode }: {
  canDelete: boolean;
  canDownload: boolean;
  dragging: boolean;
  folder: StorageFolder;
  onDelete: () => void;
  onDownload: () => void;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLElement>, folder: StorageFolder) => void;
  onLongPress: () => void;
  onOpen: () => void;
  onDropStorageItem: (event: DragEvent<HTMLElement>, folder: StorageFolder) => void;
  onDropStatus: (event: DragEvent<HTMLElement>, folder: StorageFolder) => StorageMoveDropStatus;
  onShowDetails: () => void;
  onToggleSelection: () => void;
  selected: boolean;
  selectionMode: boolean;
}) {
  const [dropStatus, setDropStatus] = useState<'idle' | 'ready' | 'blocked'>('idle');
  const { cancelLongPress, longPressHandlers } = useLongPressSelection({
    disabled: !canDelete,
    item: folder,
    onLongPress,
    shouldIgnoreTarget: isFolderLongPressIgnored,
  });

  function handleStorageDrag(event: DragEvent<HTMLElement>) {
    const status = onDropStatus(event, folder);
    if (status === 'none') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = status === 'ready' ? 'move' : 'none';
    setDropStatus(status);
  }

  function handleStorageDragLeave(event: DragEvent<HTMLElement>) {
    if (onDropStatus(event, folder) === 'none') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropStatus('idle');
  }

  function handleStorageDrop(event: DragEvent<HTMLElement>) {
    const status = onDropStatus(event, folder);
    if (status === 'none') {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropStatus('idle');
    onDropStorageItem(event, folder);
  }

  function handleOpen() {
    if (selectionMode && canDelete) {
      onToggleSelection();
      return;
    }
    onOpen();
  }

  function handleDragStart(event: DragEvent<HTMLElement>) {
    cancelLongPress();
    onDragStart(event, folder);
  }

  return (
    <article
      className={`folder-card ${dropStatus === 'ready' ? 'drop-ready' : dropStatus === 'blocked' ? 'drop-blocked' : ''} ${selectionMode ? 'selection-mode' : ''} ${selected ? 'selection-selected' : ''} ${dragging ? 'is-dragging' : ''}`}
      onDragEnter={handleStorageDrag}
      onDragLeave={handleStorageDragLeave}
      onDragOver={handleStorageDrag}
      onDrop={handleStorageDrop}
      draggable={canDelete}
      onDragEnd={onDragEnd}
      onDragStart={handleDragStart}
      {...longPressHandlers}
    >
      {selectionMode ? (
        <button
          aria-label={`${selected ? 'Deselect' : 'Select'} ${folder.name}`}
          aria-pressed={selected}
          className={`storage-selection-toggle ${selected ? 'selected' : ''}`}
          disabled={!canDelete}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (canDelete) onToggleSelection();
          }}
          title={canDelete ? `${selected ? 'Deselect' : 'Select'} ${folder.name}` : 'Storage roots cannot be selected'}
          type="button"
        >
          <span className="storage-selection-toggle-box">
            {selected ? <Icon name="check" /> : null}
          </span>
        </button>
      ) : null}
      <button className="folder-card-open" type="button" onClick={handleOpen}>
        <Icon name="folder" className="folder-card-icon storage-folder-drag-icon-source" />
        <span className="folder-card-main">
          <strong>{folder.name}</strong>
        </span>
      </button>
      <div className="folder-card-actions" aria-label={`Actions for ${folder.name}`}>
        <button className="animated-file-action folder-card-action" aria-label={`Show details for ${folder.name}`} onClick={onShowDetails} title="Details" type="button">
          <Icon name="info" />
        </button>
        <button className="animated-file-action folder-card-action" aria-label={`Download ${folder.name}`} disabled={!canDownload} onClick={onDownload} title={canDownload ? 'Download' : 'Download is not available'} type="button">
          <Icon name="download" />
        </button>
        <button
          className="animated-file-action folder-card-action danger"
          aria-label={`Delete ${folder.name}`}
          disabled={!canDelete}
          onClick={onDelete}
          title={canDelete ? 'Delete' : 'Storage roots cannot be deleted'}
          type="button"
        >
          <Icon name="delete" />
        </button>
      </div>
    </article>
  );
}

function isFolderLongPressIgnored(target: EventTarget | null) {
  const element = target instanceof Element ? target : null;
  return Boolean(element?.closest('.folder-card-actions, .storage-selection-toggle'));
}

function App() {
  const storageAppId = useMemo(() => currentStorageAppId(), []);
  const [files, setFiles] = useState<StorageFile[]>([]);
  const [folders, setFolders] = useState<StorageFolder[]>([]);
  const [catalogPagination, setCatalogPagination] = useState<CatalogPayload['pagination'] | null>(null);
  const [catalogLoadingMore, setCatalogLoadingMore] = useState(false);
  const [selectedFile, setSelectedFile] = useState<StorageFile | null>(null);
  const [activeRole, setActiveRole] = useState<FileRole | 'all'>('all');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [currentFolderPath, setCurrentFolderPath] = useState('');
  const [draggedFile, setDraggedFile] = useState<StorageFile | null>(null);
  const [draggedFolder, setDraggedFolder] = useState<StorageFolder | null>(null);
  const [draggingSelection, setDraggingSelection] = useState<DraggingSelectionState | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(() => new Set());
  const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(() => new Set());
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isCatalogTransitionLoading, setIsCatalogTransitionLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragDepth, setDragDepth] = useState(0);
  const [dropFeedback, setDropFeedback] = useState<DropFeedback>('idle');
  const [dropMessage, setDropMessage] = useState('');
  const [layoutMode, setLayoutMode] = useState<CollectionViewMode>(initialLayoutMode);
  const [viewMode, setViewMode] = useState<'search' | 'custom'>('search');
  const [customTitle, setCustomTitle] = useState('');
  const [customFileIds, setCustomFileIds] = useState<string[]>([]);
  const [customWorkspacePaths, setCustomWorkspacePaths] = useState<string[]>([]);
  const [driveTarget, setDriveTarget] = useState<DriveFolderTarget | null>(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewTable, setPreviewTable] = useState<PreviewTablePayload | undefined>(undefined);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [previewFullscreenMode, setPreviewFullscreenMode] = useState<PreviewFullscreenMode>('none');
  const [previewImageSize, setPreviewImageSize] = useState<PreviewImageSize | null>(null);
  const [previewViewportSize, setPreviewViewportSize] = useState<PreviewImageSize>(() => ({ width: window.innerWidth, height: window.innerHeight }));
  const [previewHeaderHeight, setPreviewHeaderHeight] = useState(72);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<StorageFolder | null>(null);
  const [folderDetailsOpen, setFolderDetailsOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [markdownEditing, setMarkdownEditing] = useState(false);
  const [markdownDraft, setMarkdownDraft] = useState('');
  const [markdownSaving, setMarkdownSaving] = useState(false);
  const [markdownCopying, setMarkdownCopying] = useState(false);
  const [markdownCopied, setMarkdownCopied] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [error, setError] = useState('');
  const viewFilterUpdatedAtRef = useRef<string | null>(null);
  const viewFilterWriteRef = useRef<number | null>(null);
  const viewFilterPendingRef = useRef(false);
  const markdownCopyTimerRef = useRef<number | null>(null);
  const dropFeedbackTimerRef = useRef<number | null>(null);
  const previewModalRef = useRef<HTMLElement | null>(null);
  const previewHeaderRef = useRef<HTMLElement | null>(null);
  const filesRef = useRef<StorageFile[]>([]);
  const draggedSelectionRef = useRef<StorageSelectionDragPayload | null>(null);
  const catalogLoadedCountRef = useRef(0);
  const currentFolderPathRef = useRef('');
  const customFileIdsRef = useRef<string[]>([]);
  const customWorkspacePathsRef = useRef<string[]>([]);
  const queryRef = useRef('');
  const activeRoleRef = useRef<FileRole | 'all'>('all');
  const kindRef = useRef<PreviewKind | 'all'>('all');
  const viewModeRef = useRef<'search' | 'custom'>('search');
  const driveTargetRef = useRef<DriveFolderTarget | null>(null);
  const catalogRefreshRequestRef = useRef(0);
  const catalogTransitionMinRequestRef = useRef<number | null>(null);
  const catalogTransitionTokenRef = useRef(0);
  const pendingNavigationTargetRef = useRef<StorageNavigationTarget | null>(storageTargetFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())));
  const previewFullscreenActive = previewFullscreenMode !== 'none';
  const isDriveView = Boolean(driveTarget);

  function setCurrentFolderPathScoped(path: string) {
    const normalizedPath = normalizeFolderPath(path);
    currentFolderPathRef.current = normalizedPath;
    setCurrentFolderPath(normalizedPath);
  }

  function beginCatalogTransitionLoading(minRequestId = catalogRefreshRequestRef.current + 1) {
    const token = ++catalogTransitionTokenRef.current;
    catalogTransitionMinRequestRef.current = minRequestId;
    setIsCatalogTransitionLoading(true);
    return token;
  }

  function clearCatalogTransitionLoading(token?: number) {
    if (token !== undefined && token !== catalogTransitionTokenRef.current) {
      return;
    }
    catalogTransitionMinRequestRef.current = null;
    setIsCatalogTransitionLoading(false);
  }

  function settleCatalogTransitionLoading(requestId: number) {
    const minRequestId = catalogTransitionMinRequestRef.current;
    if (minRequestId !== null && requestId === catalogRefreshRequestRef.current && requestId >= minRequestId) {
      clearCatalogTransitionLoading();
    }
  }

  function applyRemoteViewFilter(filter: StorageViewFilter) {
    if (viewFilterPendingRef.current || (viewFilterUpdatedAtRef.current !== null && filter.updated_at === viewFilterUpdatedAtRef.current)) {
      return false;
    }
    viewFilterUpdatedAtRef.current = filter.updated_at;
    viewModeRef.current = filter.mode;
    customFileIdsRef.current = filter.file_ids;
    customWorkspacePathsRef.current = filter.workspace_relative_paths;
    queryRef.current = filter.query;
    activeRoleRef.current = filter.role;
    kindRef.current = filter.kind;
    setViewMode(filter.mode);
    setCustomTitle(filter.title);
    setCustomFileIds(filter.file_ids);
    setCustomWorkspacePaths(filter.workspace_relative_paths);
    setQuery(filter.query);
    setActiveRole(filter.role);
    setKind(filter.kind);
    return true;
  }

  function refreshForViewFilter(filter: StorageViewFilter) {
    return refresh(
      { query: filter.query, role: filter.role, kind: filter.kind },
      {
        fileIds: filter.mode === 'custom' ? filter.file_ids : [],
        loading: 'foreground',
        viewMode: filter.mode,
        workspacePaths: filter.mode === 'custom' ? filter.workspace_relative_paths : [],
      }
    );
  }

  function applyLocalCatalogDelta(delta: StorageCatalogDelta) {
    catalogRefreshRequestRef.current += 1;
    setFiles((current) => {
      const nextFiles = applyStorageFilesDelta(current, delta);
      filesRef.current = nextFiles;
      catalogLoadedCountRef.current = nextFiles.length;
      return nextFiles;
    });
    setFolders((current) => {
      const nextFolders = applyStorageFoldersDelta(current, delta);
      return nextFolders;
    });
    setCatalogPagination(null);
  }

  function revalidateCatalog(
    filter?: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>,
    options: CatalogRefreshOptions = {}
  ) {
    refresh(filter, options).catch((err: Error) => setError(err.message));
  }

  async function loadDriveFolder(target: DriveFolderTarget, loading: CatalogRefreshLoading = 'foreground') {
    const requestId = ++catalogRefreshRequestRef.current;
    const transitionToken = loading === 'foreground' ? beginCatalogTransitionLoading(requestId) : null;
    try {
      const payload = target.driveFileId
        ? await listDriveChildren(target.connectionId, target.driveFileId, { limit: CATALOG_PAGE_LIMIT })
        : await listDriveRoots(target.connectionId, { limit: CATALOG_PAGE_LIMIT });
      if (requestId !== catalogRefreshRequestRef.current) return;
      const nextFiles = payload.files || [];
      const nextFolders = payload.folders || [];
      filesRef.current = nextFiles;
      catalogLoadedCountRef.current = driveLoadedItemCount(nextFiles, nextFolders);
      setFiles(nextFiles);
      setFolders(nextFolders);
      setCatalogPagination(payload.pagination ? { offset: 0, ...payload.pagination } : null);
      setSelectedFile(null);
      setSelectedFolder(null);
      closePreviewModal();
      setDetailsOpen(false);
      setFolderDetailsOpen(false);
      clearSelectionMode();
      setCurrentFolderPathScoped('');
      setActiveRole('all');
      activeRoleRef.current = 'all';
      setKind('all');
      kindRef.current = 'all';
      setViewMode('search');
      viewModeRef.current = 'search';
      setCustomTitle('');
      setCustomFileIds([]);
      setCustomWorkspacePaths([]);
      setDriveTarget(target);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Google Drive folder.');
    } finally {
      if (transitionToken !== null) {
        clearCatalogTransitionLoading(transitionToken);
      } else {
        settleCatalogTransitionLoading(requestId);
      }
    }
  }

  function catalogRequest(
    filter?: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>,
    offset = 0,
    options: CatalogRequestOptions = {}
  ) {
    const catalogFilter = {
      query: filter?.query ?? queryRef.current,
      role: filter?.role ?? activeRoleRef.current,
      kind: filter?.kind ?? kindRef.current,
    };
    const effectiveViewMode = options.viewMode ?? viewModeRef.current;
    const effectiveFileIds = options.fileIds ?? customFileIdsRef.current;
    const effectiveWorkspacePaths = options.workspacePaths ?? customWorkspacePathsRef.current;
    const scopedFolderPath = !catalogFilter.query.trim() && catalogFilter.role !== 'all' && effectiveViewMode !== 'custom'
      ? options.folderPath ?? currentFolderPathRef.current
      : undefined;
    return {
      ...catalogFilter,
      ...(scopedFolderPath === undefined ? {} : { folder_path: scopedFolderPath }),
      ...(effectiveViewMode === 'custom' && effectiveFileIds.length ? { file_ids: effectiveFileIds } : {}),
      ...(effectiveViewMode === 'custom' && effectiveWorkspacePaths.length ? { workspace_relative_paths: effectiveWorkspacePaths } : {}),
      offset,
      limit: CATALOG_PAGE_LIMIT,
    };
  }

  async function refresh(
    filter?: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>,
    options: CatalogRefreshOptions = {}
  ) {
    if (driveTargetRef.current) {
      await loadDriveFolder(driveTargetRef.current, options.loading ?? 'background');
      return;
    }
    const requestId = ++catalogRefreshRequestRef.current;
    const { loading = 'background', ...requestOptions } = options;
    if (loading === 'foreground') {
      beginCatalogTransitionLoading(requestId);
    }
    try {
      let request = catalogRequest(filter, 0, requestOptions);
      let payload = await loadCatalog(request);
      if (requestId !== catalogRefreshRequestRef.current) return;
      let remoteFilter = normalizedViewFilter(payload.state.view_filter);
      if (remoteFilter.mode === 'custom' && !request.file_ids?.length && !request.workspace_relative_paths?.length) {
        request = catalogRequest(
          { query: remoteFilter.query, role: remoteFilter.role, kind: remoteFilter.kind },
          0,
          {
            fileIds: remoteFilter.file_ids,
            folderPath: requestOptions.folderPath,
            viewMode: remoteFilter.mode,
            workspacePaths: remoteFilter.workspace_relative_paths,
          }
        );
        payload = await loadCatalog(request);
        if (requestId !== catalogRefreshRequestRef.current) return;
        remoteFilter = normalizedViewFilter(payload.state.view_filter);
      }
      filesRef.current = payload.files;
      catalogLoadedCountRef.current = catalogLoadedCountAfterRefresh(payload.files.length);
      setFiles(payload.files);
      setFolders(payload.folders || []);
      setCatalogPagination(payload.pagination || null);
      applyRemoteViewFilter(remoteFilter);
      const pendingFile = fileFromNavigationTarget(payload.files, pendingNavigationTargetRef.current);
      if (pendingFile) {
        pendingNavigationTargetRef.current = null;
        await focusResolvedNavigationFile(pendingFile);
      } else if (pendingNavigationTargetRef.current?.targetType === 'file') {
        const target = pendingNavigationTargetRef.current;
        const targetFile = await loadNavigationTarget(target);
        if (targetFile) {
          pendingNavigationTargetRef.current = null;
          await focusResolvedNavigationFile(targetFile);
        } else {
          const fallbackTarget = folderTargetFromMissingFileTarget(target);
          if (fallbackTarget?.role) {
            pendingNavigationTargetRef.current = null;
            setSelectedFile(null);
            setDetailsOpen(false);
            closePreviewModal();
            setCurrentFolderPathScoped(fallbackTarget.folderRelativePath || '');
            setError('');
            updateViewFilter(
              { query: '', role: fallbackTarget.role, kind: 'all' },
              { folderPath: fallbackTarget.folderRelativePath || '', preserveCustom: false }
            );
            return;
          }
          const missingTarget = missingNavigationTargetPlan();
          if (missingTarget.clearPending) pendingNavigationTargetRef.current = null;
          setError(missingTarget.error);
        }
      }
    } finally {
      settleCatalogTransitionLoading(requestId);
    }
  }

  async function loadNavigationTarget(target: StorageNavigationTarget) {
    if (!target.fileId && !target.workspaceRelativePath) return null;
    const payload = await loadCatalog({
      ...(target.fileId ? { file_ids: [target.fileId] } : {}),
      ...(target.workspaceRelativePath ? { workspace_relative_paths: [target.workspaceRelativePath] } : {}),
      limit: 1,
      offset: 0,
    });
    return payload.files[0] || null;
  }

  async function loadMoreFiles() {
    if (!catalogPagination?.has_more || catalogLoadingMore) return;
    setCatalogLoadingMore(true);
    try {
      const driveTarget = driveTargetRef.current;
      if (driveTarget) {
        const nextLimit = Math.max(CATALOG_PAGE_LIMIT, catalogLoadedCountRef.current + CATALOG_PAGE_LIMIT);
        const payload = driveTarget.driveFileId
          ? await listDriveChildren(driveTarget.connectionId, driveTarget.driveFileId, { limit: nextLimit })
          : await listDriveRoots(driveTarget.connectionId, { limit: nextLimit });
        const nextFiles = payload.files || [];
        const nextFolders = payload.folders || [];
        catalogLoadedCountRef.current = driveLoadedItemCount(nextFiles, nextFolders);
        filesRef.current = nextFiles;
        setFiles(nextFiles);
        setFolders(nextFolders);
        setCatalogPagination(payload.pagination ? { offset: 0, ...payload.pagination } : null);
        setError('');
        return;
      }
      const payload = await loadCatalog(catalogRequest(undefined, catalogLoadedCountRef.current));
      catalogLoadedCountRef.current = catalogLoadedCountAfterPage(catalogLoadedCountRef.current, payload.files.length);
      const nextFiles = mergeUniqueFiles(filesRef.current, payload.files);
      filesRef.current = nextFiles;
      setFiles(nextFiles);
      setFolders(payload.folders || []);
      setCatalogPagination(payload.pagination || null);
      setError('');
    } finally {
      setCatalogLoadingMore(false);
    }
  }

  async function syncViewFilter() {
    const payload = await loadViewFilter();
    const remoteFilter = normalizedViewFilter(payload.state.view_filter);
    if (applyRemoteViewFilter(remoteFilter)) {
      await refreshForViewFilter(remoteFilter);
    }
  }

  async function handleDriveOAuthCallback(callback: StorageOAuthCallback) {
    const appId = callback.appId || storageAppId;
    setError('');
    if (callback.error) {
      await refresh();
      setError(`Google Drive authorization failed: ${callback.error}.`);
      return;
    }
    if (!callback.code || !callback.state) {
      await refresh();
      setError('Google Drive authorization callback is missing code or state. Start the connection again.');
      return;
    }
    try {
      await completeDriveOAuth(
        { code: callback.code, redirectUri: callback.redirectUri, state: callback.state },
        { appId },
      );
      await refresh();
      window.history.replaceState({}, '', `/apps/${encodeURIComponent(appId)}/`);
    } catch (oauthError) {
      await refresh();
      setError(oauthError instanceof Error ? oauthError.message : 'Google Drive connection failed.');
    }
  }

  useEffect(() => {
    const oauthCallback = storageOAuthCallbackFromLocation(window.location.pathname, window.location.search, window.location.origin);
    const initialTarget = oauthCallback ? null : pendingNavigationTargetRef.current;
    const initialLoad = oauthCallback
      ? handleDriveOAuthCallback(oauthCallback)
      : initialTarget?.provider === 'google_drive' && initialTarget.connectionId
      ? loadDriveFolder({
        connectionId: initialTarget.connectionId,
        displayPath: initialTarget.displayPath || 'Google Drive',
        driveFileId: initialTarget.driveFileId || '',
      })
      : refresh();
    initialLoad
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        if (initialTarget?.provider === 'google_drive') {
          pendingNavigationTargetRef.current = null;
        }
        setIsInitialLoading(false);
      });
    const interval = window.setInterval(() => {
      syncViewFilter().catch((err: Error) => setError(err.message));
    }, VIEW_SYNC_MS);
    return () => {
      window.clearInterval(interval);
      if (viewFilterWriteRef.current !== null) window.clearTimeout(viewFilterWriteRef.current);
      if (markdownCopyTimerRef.current !== null) window.clearTimeout(markdownCopyTimerRef.current);
      if (dropFeedbackTimerRef.current !== null) window.clearTimeout(dropFeedbackTimerRef.current);
    };
  }, []);

  useEffect(() => {
    filesRef.current = files;
  }, [files]);

  useEffect(() => {
    queryRef.current = query;
  }, [query]);

  useEffect(() => {
    activeRoleRef.current = activeRole;
  }, [activeRole]);

  useEffect(() => {
    currentFolderPathRef.current = currentFolderPath;
  }, [currentFolderPath]);

  useEffect(() => {
    customFileIdsRef.current = customFileIds;
  }, [customFileIds]);

  useEffect(() => {
    customWorkspacePathsRef.current = customWorkspacePaths;
  }, [customWorkspacePaths]);

  useEffect(() => {
    kindRef.current = kind as PreviewKind | 'all';
  }, [kind]);

  useEffect(() => {
    viewModeRef.current = viewMode;
  }, [viewMode]);

  useEffect(() => {
    driveTargetRef.current = driveTarget;
  }, [driveTarget]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'storage' }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: StorageNavigationParams;
        resource?: string;
        type?: string;
      };
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === storageAppId)) {
        handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === storageAppId) {
        if (payload.resource === 'files' || payload.resource === 'drive-connections') {
          refresh().catch((err: Error) => setError(err.message));
        }
        if (payload.resource === 'view-state') {
          const detailedFilter = storageViewFilterFromMessage(payload, storageAppId);
          if (detailedFilter) {
            const remoteFilter = normalizedViewFilter(detailedFilter);
            if (applyRemoteViewFilter(remoteFilter)) {
              refreshForViewFilter(remoteFilter).catch((err: Error) => setError(err.message));
            }
            return;
          }
          syncViewFilter().catch((err: Error) => setError(err.message));
        }
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  useEffect(() => {
    if (selectedFile) {
      notifyActiveStorageSelection(selectedFile);
    }
  }, [selectedFile]);

  useEffect(() => {
    if (!previewModalOpen && !detailsOpen && !folderDetailsOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (previewFullscreenActive) {
          exitPreviewFullscreenIfNeeded();
          return;
        }
        closePreviewModal();
        setDetailsOpen(false);
        setFolderDetailsOpen(false);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [detailsOpen, folderDetailsOpen, previewFullscreenActive, previewModalOpen]);

  function updateViewFilter(
    filter: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>,
    options: { folderPath?: string; loading?: CatalogRefreshLoading; preserveCustom?: boolean } = {}
  ) {
    const preserveCustom = options.preserveCustom ?? viewMode === 'custom';
    const loading = options.loading ?? 'foreground';
    const transitionToken = loading === 'foreground' ? beginCatalogTransitionLoading() : null;
    const next = normalizedViewFilter({ query, role: activeRole, kind: kind as PreviewKind | 'all', ...filter });
    queryRef.current = next.query;
    activeRoleRef.current = next.role;
    kindRef.current = next.kind;
    setQuery(next.query);
    setActiveRole(next.role);
    setKind(next.kind);
    if (!preserveCustom) {
      viewModeRef.current = 'search';
      customFileIdsRef.current = [];
      customWorkspacePathsRef.current = [];
      setViewMode('search');
      setCustomTitle('');
      setCustomFileIds([]);
      setCustomWorkspacePaths([]);
    }
    viewFilterPendingRef.current = true;
    if (viewFilterWriteRef.current !== null) window.clearTimeout(viewFilterWriteRef.current);
    viewFilterWriteRef.current = window.setTimeout(() => {
      let refreshStarted = false;
      setViewFilter({ query: next.query, role: next.role, kind: next.kind, preserve_custom: preserveCustom })
        .then((payload) => {
          const remote = normalizedViewFilter(payload.state.view_filter);
          viewFilterUpdatedAtRef.current = remote.updated_at;
          refreshStarted = true;
          return refresh(
            { query: remote.query, role: remote.role, kind: remote.kind },
            {
              fileIds: preserveCustom ? remote.file_ids : [],
              folderPath: options.folderPath,
              loading,
              viewMode: preserveCustom ? remote.mode : 'search',
              workspacePaths: preserveCustom ? remote.workspace_relative_paths : [],
            }
          );
        })
        .catch((err: Error) => {
          setError(err.message);
          if (!refreshStarted && transitionToken !== null) {
            clearCatalogTransitionLoading(transitionToken);
          }
        })
        .finally(() => {
          viewFilterPendingRef.current = false;
          viewFilterWriteRef.current = null;
        });
    }, 250);
  }

  async function focusResolvedNavigationFile(file: StorageFile) {
    const transitionToken = beginCatalogTransitionLoading();
    const plan = resolvedFileNavigationPlan(file);
    queryRef.current = plan.filter.query;
    activeRoleRef.current = plan.filter.role;
    kindRef.current = plan.filter.kind;
    viewModeRef.current = 'search';
    customFileIdsRef.current = [];
    customWorkspacePathsRef.current = [];
    setQuery(plan.filter.query);
    setActiveRole(plan.filter.role);
    setKind(plan.filter.kind);
    setViewMode('search');
    setCustomTitle('');
    setCustomFileIds([]);
    setCustomWorkspacePaths([]);
    setCurrentFolderPathScoped(plan.folderPath);

    try {
      const payload = await loadCatalog(catalogRequest(plan.filter, 0, plan.refreshOptions));
      const nextFiles = mergeUniqueFiles(payload.files, [file]);
      filesRef.current = nextFiles;
      catalogLoadedCountRef.current = catalogLoadedCountAfterRefresh(payload.files.length);
      setFiles(nextFiles);
      setFolders(payload.folders || []);
      setCatalogPagination(payload.pagination || null);
      focusFile(file, { persistFilter: true, preserveCustom: false, query: plan.filter.query });
    } finally {
      clearCatalogTransitionLoading(transitionToken);
    }
  }

  function focusFile(file: StorageFile, options: { persistFilter?: boolean; preserveCustom?: boolean; query?: string } = {}) {
    if (!isFileRole(file.role)) {
      setSelectedFile(file);
      return;
    }
    const fileFolder = fileFolderSelection(file);
    const nextQuery = options.query ?? queryRef.current;
    setSelectedFile(file);
    setCurrentFolderPathScoped(fileFolder.relativePath);
    setActiveRole(fileFolder.role);
    activeRoleRef.current = fileFolder.role;
    setKind('all');
    kindRef.current = 'all';
    if (options.query !== undefined) {
      queryRef.current = options.query;
      setQuery(options.query);
    }
    if (options.persistFilter) {
      viewFilterPendingRef.current = true;
      if (viewFilterWriteRef.current !== null) window.clearTimeout(viewFilterWriteRef.current);
      setViewFilter({
        query: nextQuery,
        role: file.role,
        kind: 'all',
        preserve_custom: options.preserveCustom ?? (viewModeRef.current === 'custom')
      })
        .then((payload) => {
          const remote = normalizedViewFilter(payload.state.view_filter);
          viewFilterUpdatedAtRef.current = remote.updated_at;
        })
        .catch((err: Error) => setError(err.message))
        .finally(() => {
          viewFilterPendingRef.current = false;
          viewFilterWriteRef.current = null;
        });
    }
  }

  function handleNavigationParams(params: StorageNavigationParams) {
    const target = storageTargetFromParams(params);
    if (!target) {
      return;
    }
    if (target.provider === 'google_drive' && target.connectionId) {
      const nextTarget = {
        connectionId: target.connectionId,
        displayPath: target.displayPath || 'Google Drive',
        driveFileId: target.driveFileId || '',
      };
      pendingNavigationTargetRef.current = null;
      loadDriveFolder(nextTarget, 'foreground').catch((err: Error) => setError(err.message));
      return;
    }
    setDriveTarget(null);
    driveTargetRef.current = null;
    if (target.targetType === 'folder') {
      const targetFolderPath = target.folderRelativePath || '';
      setCurrentFolderPathScoped(targetFolderPath);
      if (target.role) {
        updateViewFilter({ query: '', role: target.role }, { folderPath: targetFolderPath, preserveCustom: false });
      } else {
        refresh({ query: '' }, { folderPath: targetFolderPath, loading: 'foreground' }).catch((err: Error) => setError(err.message));
      }
      pendingNavigationTargetRef.current = null;
      return;
    }
    pendingNavigationTargetRef.current = target;
    const file = fileFromNavigationTarget(filesRef.current, target);
    if (file) {
      pendingNavigationTargetRef.current = null;
      focusResolvedNavigationFile(file).catch((err: Error) => setError(err.message));
      return;
    }
    refresh(undefined, { loading: 'foreground' }).catch((err: Error) => setError(err.message));
  }

  function clearCustomFileView() {
    clearCustomView()
      .then((payload) => {
        const remote = normalizedViewFilter(payload.state.view_filter);
        applyRemoteViewFilter(remote);
        return refresh(
          { query: remote.query, role: remote.role, kind: remote.kind },
          {
            fileIds: remote.file_ids,
            loading: 'foreground',
            viewMode: remote.mode,
            workspacePaths: remote.workspace_relative_paths,
          }
        );
      })
      .catch((err: Error) => setError(err.message));
  }

  function chooseLayoutMode(nextMode: CollectionViewMode) {
    setLayoutMode(nextMode);
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, nextMode);
  }

  function openFolder(folder: StorageFolder) {
    if (isDriveItem(folder)) {
      if (!folder.connection_id || !folder.drive_file_id) {
        setError('Google Drive folder identity is missing.');
        return;
      }
      const nextTarget = {
        connectionId: folder.connection_id,
        displayPath: folder.display_path || folder.name,
        driveFileId: folder.drive_file_id,
      };
      loadDriveFolder(nextTarget, 'foreground').catch((err: Error) => setError(err.message));
      notifyActiveStorageFolderSelection(folder);
      return;
    }
    if (!isFileRole(folder.role)) {
      setError('This folder is not a local Storage folder.');
      return;
    }
    const plan = folderOpenRefreshPlan({
      activeRole,
      folderPath: folder.relative_path,
      folderRole: folder.role,
      query,
      viewMode,
    });
    setCurrentFolderPathScoped(plan.folderPath);
    if (plan.shouldWriteViewFilter) {
      updateViewFilter(plan.filter, plan.viewFilterOptions);
    } else {
      refresh(plan.filter, { ...plan.refreshOptions, loading: 'foreground' }).catch((err: Error) => setError(err.message));
    }
    notifyActiveStorageFolderSelection(folder);
  }

  function clearDropFeedbackLater() {
    if (dropFeedbackTimerRef.current !== null) window.clearTimeout(dropFeedbackTimerRef.current);
    dropFeedbackTimerRef.current = window.setTimeout(() => {
      setDropFeedback('idle');
      setDropMessage('');
      dropFeedbackTimerRef.current = null;
    }, 1400);
  }

  function openFilePreview(file: StorageFile) {
    if (isDriveItem(file)) {
      showFileDetails(file);
      return;
    }
    setPreviewText('');
    setPreviewUrl('');
    setPreviewTable(undefined);
    setPreviewImageSize(null);
    setPreviewLoading(canInlinePreview(file));
    setSelectedFile(file);
    setDetailsOpen(false);
    setPreviewModalOpen(true);
  }

  function exitPreviewFullscreenIfNeeded() {
    if (elementIsFullscreen(previewModalRef.current)) {
      exitDocumentFullscreen().catch(() => undefined);
    }
    setPreviewFullscreenMode('none');
  }

  function closePreviewModal() {
    exitPreviewFullscreenIfNeeded();
    setPreviewModalOpen(false);
  }

  async function togglePreviewFullscreen() {
    if (previewFullscreenActive) {
      exitPreviewFullscreenIfNeeded();
      return;
    }
    const previewModal = previewModalRef.current;
    if (!previewModal) return;
    if (canRequestFullscreen(previewModal)) {
      try {
        await requestElementFullscreen(previewModal);
        setPreviewFullscreenMode('native');
        return;
      } catch {
        // Fall through to an in-app fullscreen layout when iframe policy blocks native fullscreen.
      }
    }
    setPreviewFullscreenMode('expanded');
  }

  function showFileDetails(file: StorageFile) {
    setSelectedFile(file);
    closePreviewModal();
    setDetailsOpen(true);
    setFolderDetailsOpen(false);
  }

  function showFolderDetails(folder: StorageFolder) {
    setSelectedFolder(folder);
    closePreviewModal();
    setDetailsOpen(false);
    setFolderDetailsOpen(true);
  }

  function clearSelectionMode() {
    setSelectionMode(false);
    setSelectedFileIds(new Set());
    setSelectedFolderIds(new Set());
  }

  function activateFileSelection(file: StorageFile) {
    if (isDriveItem(file)) return;
    setSelectionMode(true);
    setSelectedFileIds((current) => new Set(current).add(file.id));
  }

  function activateFolderSelection(folder: StorageFolder) {
    if (isDriveItem(folder) || !folder.relative_path) return;
    setSelectionMode(true);
    setSelectedFolderIds((current) => new Set(current).add(folder.id));
  }

  function toggleFileSelection(file: StorageFile) {
    if (isDriveItem(file)) return;
    setSelectionMode(true);
    setSelectedFileIds((current) => {
      const next = new Set(current);
      if (next.has(file.id)) {
        next.delete(file.id);
      } else {
        next.add(file.id);
      }
      return next;
    });
  }

  function toggleFolderSelection(folder: StorageFolder) {
    if (isDriveItem(folder) || !folder.relative_path) return;
    setSelectionMode(true);
    setSelectedFolderIds((current) => {
      const next = new Set(current);
      if (next.has(folder.id)) {
        next.delete(folder.id);
      } else {
        next.add(folder.id);
      }
      return next;
    });
  }

  const customScopedFiles = useMemo(() => {
    if (isDriveView) {
      return files;
    }
    return storageCustomScopedFiles({
      fileIds: customFileIds,
      files,
      viewMode,
      workspaceRelativePaths: customWorkspacePaths,
    });
  }, [customFileIds, customWorkspacePaths, files, isDriveView, viewMode]);

  const browsableFolders = useMemo(() => {
    if (isDriveView) {
      return folders;
    }
    const roots = storageRootRoles.map((role) => {
      return folders.find((folder) => folder.role === role && !folder.relative_path) || storageRootFolder(role);
    });
    return [
      ...roots,
      ...folders.filter((folder) => folder.relative_path)
    ];
  }, [folders, isDriveView]);

  const visibleFolders = useMemo(() => {
    if (isDriveView) {
      const needle = query.trim().toLowerCase();
      return folders.filter((folder) => !needle || `${folder.name} ${folder.display_path || ''}`.toLowerCase().includes(needle));
    }
    return storageViewVisibleFolders({
      activeRole,
      browsableFolders,
      currentFolderPath,
      folders,
      query,
      viewMode,
    });
  }, [activeRole, browsableFolders, currentFolderPath, folders, isDriveView, query, viewMode]);

  const filteredFiles = useMemo(() => {
    if (isDriveView) {
      const needle = query.trim().toLowerCase();
      return files.filter((file) => {
        const kindMatch = kind === 'all' || file.preview_kind === kind;
        const textMatch = !needle || `${file.name} ${file.display_path || ''} ${file.content_type}`.toLowerCase().includes(needle);
        return kindMatch && textMatch;
      });
    }
    return storageViewVisibleFiles({
      activeRole,
      currentFolderPath,
      files: customScopedFiles,
      kind,
      query,
      viewMode,
    });
  }, [activeRole, currentFolderPath, customScopedFiles, files, isDriveView, kind, query, viewMode]);
  const selectedFiles = useMemo(() => filteredFiles.filter((file) => selectedFileIds.has(file.id)), [filteredFiles, selectedFileIds]);
  const selectedFolders = useMemo(() => visibleFolders.filter((folder) => selectedFolderIds.has(folder.id) && Boolean(folder.relative_path)), [selectedFolderIds, visibleFolders]);
  const selectedMoveItems = useMemo(() => storageSelectionMovePlan(selectedFiles, selectedFolders), [selectedFiles, selectedFolders]);
  const selectedItemCount = selectedFiles.length + selectedFolders.length;
  const draggingFileIds = draggingSelection?.fileIds || emptyIdSet;
  const draggingFolderIds = draggingSelection?.folderIds || emptyIdSet;
  const selectedFolderStats = useMemo(() => {
    if (!selectedFolder) return null;
    if (isDriveItem(selectedFolder) || !isFileRole(selectedFolder.role)) {
      return {
        fileCount: 0,
        folderCount: 0,
        sizeBytes: 0,
      };
    }
    return folderStatsForSelection({ role: selectedFolder.role, relativePath: selectedFolder.relative_path }, files, folders);
  }, [files, folders, selectedFolder]);
  const currentFolderStats = useMemo(() => {
    if (isDriveView) {
      return {
        fileCount: filteredFiles.length,
        folderCount: visibleFolders.length,
        sizeBytes: filteredFiles.reduce((total, file) => total + file.size_bytes, 0),
      };
    }
    return folderStatsForSelection({ role: activeRole, relativePath: activeRole === 'all' ? '' : currentFolderPath }, files, folders);
  }, [activeRole, currentFolderPath, files, filteredFiles, folders, isDriveView, visibleFolders]);
  const catalogDisplayState = catalogBrowserDisplayState({
    initialLoading: isInitialLoading,
    transitionLoading: isCatalogTransitionLoading,
    visibleFileCount: filteredFiles.length,
    visibleFolderCount: visibleFolders.length,
  });
  const isCatalogContentLoading = catalogDisplayState === 'loading';
  const currentFolderSizeLabel = formatMegabytes(currentFolderStats.sizeBytes);
  const visibleFileTotal = catalogPagination?.total ?? filteredFiles.length;
  const fileCountLabel = visibleFileTotal > filteredFiles.length
    ? `${filteredFiles.length}/${visibleFileTotal} files`
    : `${filteredFiles.length} files`;
  const folderBreadcrumbs = isDriveView ? [] : folderBreadcrumbItems(currentFolderPath);
  const storageBreadcrumbLabel = isDriveView ? driveTarget?.displayPath || 'Google Drive' : activeRole === 'all' ? '' : roleLabels[activeRole];
  const pendingDeleteName = pendingDelete?.kind === 'file' ? pendingDelete.file.name : pendingDelete?.folder.name || '';
  const pendingDeletePath = pendingDelete?.kind === 'file'
    ? (isDriveItem(pendingDelete.file) ? driveItemPath(pendingDelete.file) : pendingDelete.file.workspace_relative_path)
    : pendingDelete?.folder
      ? (isDriveItem(pendingDelete.folder) ? driveItemPath(pendingDelete.folder) : pendingDelete.folder.workspace_relative_path)
      : '';
  const pendingDeleteTitle = pendingDelete ? `Delete ${pendingDelete.kind}?` : '';
  const pendingDeleteDescription = pendingDelete && isDriveItem(pendingDelete.kind === 'file' ? pendingDelete.file : pendingDelete.folder)
    ? 'This moves the item to Google Drive trash when Drive grants delete permission.'
    : pendingDelete?.kind === 'folder'
    ? 'This removes the folder and every file inside it from workspace storage.'
    : 'This removes the file from workspace storage.';
  const pendingDeleteActionLabel = pendingDelete?.kind === 'folder' ? 'Delete folder' : 'Delete file';

  useEffect(() => {
    const visibleFileIds = new Set(filteredFiles.map((file) => file.id));
    const visibleFolderIds = new Set(visibleFolders.filter((folder) => folder.relative_path).map((folder) => folder.id));
    setSelectedFileIds((current) => pruneSelection(current, visibleFileIds));
    setSelectedFolderIds((current) => pruneSelection(current, visibleFolderIds));
  }, [filteredFiles, visibleFolders]);

  useEffect(() => {
    if (!selectionMode) return;
    function handleSelectionKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        clearSelectionMode();
      }
    }
    window.addEventListener('keydown', handleSelectionKeyDown);
    return () => window.removeEventListener('keydown', handleSelectionKeyDown);
  }, [selectionMode]);

  useEffect(() => {
    setPreviewText('');
    setPreviewUrl('');
    setPreviewTable(undefined);
    setPreviewLoading(false);
    setMarkdownEditing(false);
    setMarkdownDraft('');
    setMarkdownCopying(false);
    if (markdownCopyTimerRef.current !== null) {
      window.clearTimeout(markdownCopyTimerRef.current);
      markdownCopyTimerRef.current = null;
    }
    setMarkdownCopied(false);
    setRenameValue(selectedFile?.name || '');
    setPreviewImageSize(null);
    if (!selectedFile) {
      closePreviewModal();
      setDetailsOpen(false);
      return;
    }
  }, [selectedFile]);

  useEffect(() => {
    if (!previewModalOpen) return;
    function updatePreviewViewportSize() {
      const previewModal = previewModalRef.current;
      if (previewFullscreenActive && previewModal) {
        const rect = previewModal.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          setPreviewViewportSize({ width: Math.floor(rect.width), height: Math.floor(rect.height) });
          return;
        }
      }
      setPreviewViewportSize({ width: window.innerWidth, height: window.innerHeight });
    }
    updatePreviewViewportSize();
    window.addEventListener('resize', updatePreviewViewportSize);
    window.addEventListener('orientationchange', updatePreviewViewportSize);
    return () => {
      window.removeEventListener('resize', updatePreviewViewportSize);
      window.removeEventListener('orientationchange', updatePreviewViewportSize);
    };
  }, [previewFullscreenActive, previewModalOpen]);

  useEffect(() => {
    if (!previewModalOpen) return;
    function syncPreviewFullscreenState() {
      if (elementIsFullscreen(previewModalRef.current)) {
        setPreviewFullscreenMode('native');
        return;
      }
      setPreviewFullscreenMode((current) => current === 'native' ? 'none' : current);
    }
    document.addEventListener('fullscreenchange', syncPreviewFullscreenState);
    document.addEventListener('webkitfullscreenchange', syncPreviewFullscreenState);
    document.addEventListener('MSFullscreenChange', syncPreviewFullscreenState);
    return () => {
      document.removeEventListener('fullscreenchange', syncPreviewFullscreenState);
      document.removeEventListener('webkitfullscreenchange', syncPreviewFullscreenState);
      document.removeEventListener('MSFullscreenChange', syncPreviewFullscreenState);
    };
  }, [previewModalOpen]);

  useEffect(() => {
    if (!previewModalOpen) return;
    const headerElement = previewHeaderRef.current;
    if (!headerElement) return;
    function updatePreviewHeaderHeight(element: HTMLElement) {
      setPreviewHeaderHeight(Math.ceil(element.getBoundingClientRect().height));
    }
    updatePreviewHeaderHeight(headerElement);
    const observer = new ResizeObserver(() => updatePreviewHeaderHeight(headerElement));
    observer.observe(headerElement);
    return () => observer.disconnect();
  }, [previewModalOpen, selectedFile]);

  useEffect(() => {
    if (!pendingDelete) return;
    function handleDeleteDialogKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !deleteBusy) setPendingDelete(null);
    }
    window.addEventListener('keydown', handleDeleteDialogKeydown);
    return () => window.removeEventListener('keydown', handleDeleteDialogKeydown);
  }, [deleteBusy, pendingDelete]);

  useEffect(() => {
    setPreviewImageSize(null);
    if (!previewModalOpen || selectedFile?.preview_kind !== 'image' || !previewUrl) return;
    let active = true;
    const image = new Image();
    image.onload = () => {
      if (!active || !image.naturalWidth || !image.naturalHeight) return;
      setPreviewImageSize({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      if (active) setPreviewImageSize(null);
    };
    image.src = previewUrl;
    return () => {
      active = false;
    };
  }, [previewModalOpen, previewUrl, selectedFile?.id, selectedFile?.preview_kind]);

  useEffect(() => {
    if (!selectedFile || (!previewModalOpen && !markdownEditing)) return;
    if (!canInlinePreview(selectedFile) && !canTextPreview(selectedFile)) return;
    let active = true;
    setPreviewLoading(true);
    loadFullPreview(selectedFile)
      .then((payload) => {
        if (!active) return;
        setPreviewText(payload.text);
        setMarkdownDraft(payload.text);
        setPreviewUrl(payload.url);
        setPreviewTable(payload.table);
      })
      .catch((err: Error) => active && setError(err.message))
      .finally(() => {
        if (active) setPreviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [markdownEditing, previewModalOpen, selectedFile]);

  const previewImageLayout = useMemo(() => {
    if (!previewModalOpen || selectedFile?.preview_kind !== 'image' || !previewImageSize) return null;
    return fittedPreviewImageSize(previewImageSize, previewViewportSize, previewHeaderHeight);
  }, [previewHeaderHeight, previewImageSize, previewModalOpen, previewViewportSize, selectedFile?.preview_kind]);

  const previewModalStyle: PreviewImageStyle | undefined = previewImageLayout && !previewFullscreenActive
    && previewViewportSize.width > 780
    ? {
      width: `${previewImageLayout.width}px`,
      '--preview-image-height': `${previewImageLayout.height}px`
    }
    : undefined;
  const previewFullscreenLabel = previewFullscreenActive ? 'Exit full screen' : 'Open preview full screen';
  const previewFullscreenIcon = previewFullscreenActive ? 'fullscreen_exit' : 'fullscreen';
  const previewModalClassName = [
    'preview-modal',
    previewImageLayout ? 'image-preview' : '',
    previewFullscreenActive ? 'is-fullscreen' : ''
  ].filter(Boolean).join(' ');
  const previewBackdropClassName = previewFullscreenActive ? 'preview-modal-backdrop is-fullscreen-preview' : 'preview-modal-backdrop';

  async function download(file: StorageFile) {
    const payload = isDriveItem(file)
      ? await readDriveFile(file, DOWNLOAD_BYTES)
      : await readFile(file, DOWNLOAD_BYTES);
    const url = URL.createObjectURL(decodeBase64(payload.content_base64, payload.file.content_type));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = payload.file.name;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function downloadFolderArchive(folder: StorageFolder) {
    const payload = await downloadFolder(folder);
    const url = URL.createObjectURL(decodeBase64(payload.content_base64, payload.content_type));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = payload.file_name;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function saveRename() {
    if (!selectedFile) return;
    if (isDriveItem(selectedFile) && !itemCan(selectedFile, 'can_rename', false)) {
      setError('Google Drive did not grant rename permission for this file.');
      return;
    }
    const payload = isDriveItem(selectedFile)
      ? await renameDriveFile(selectedFile, renameValue)
      : await renameFile(selectedFile, renameValue);
    if (isDriveItem(selectedFile)) {
      setFiles((current) => current.map((file) => file.id === selectedFile.id ? payload.file : file));
      filesRef.current = filesRef.current.map((file) => file.id === selectedFile.id ? payload.file : file);
      setSelectedFile(payload.file);
      revalidateCatalog();
      return;
    }
    applyLocalCatalogDelta({ type: 'upsert_file', file: payload.file, previous: selectedFile });
    setSelectedFile(payload.file);
    revalidateCatalog();
  }

  async function saveMarkdown() {
    if (!selectedFile || selectedFile.preview_kind !== 'markdown') return;
    setMarkdownSaving(true);
    try {
      const payload = await updateMarkdownFile(selectedFile, markdownDraft);
      applyLocalCatalogDelta({ type: 'upsert_file', file: payload.file, previous: selectedFile });
      setSelectedFile(payload.file);
      setPreviewText(markdownDraft);
      setMarkdownEditing(false);
      revalidateCatalog();
    } finally {
      setMarkdownSaving(false);
    }
  }

  async function copyMarkdownContent() {
    if (!selectedFile || selectedFile.preview_kind !== 'markdown') return;
    setMarkdownCopying(true);
    setMarkdownCopied(false);
    try {
      const text = markdownEditing
        ? markdownDraft
        : await readFullFileText(selectedFile);
      await writeClipboardText(text);
      setMarkdownCopied(true);
      if (markdownCopyTimerRef.current !== null) window.clearTimeout(markdownCopyTimerRef.current);
      markdownCopyTimerRef.current = window.setTimeout(() => {
        setMarkdownCopied(false);
        markdownCopyTimerRef.current = null;
      }, 1600);
    } finally {
      setMarkdownCopying(false);
    }
  }

  async function uploadSelectedFiles(selectedFiles: File[]) {
    if (!selectedFiles.length) {
      setDropFeedback('idle');
      setDropMessage('');
      return;
    }
    if (isDriveView) {
      setError('Google Drive upload is not supported here yet.');
      setDropFeedback('error');
      setDropMessage('Google Drive upload is not supported here yet.');
      clearDropFeedbackLater();
      return;
    }
    if (activeRole === 'all') {
      setError('Choose Generated or Uploaded before uploading a file.');
      setDropFeedback('error');
      setDropMessage('Choose Generated or Uploaded first.');
      clearDropFeedbackLater();
      return;
    }
    const targetRole = activeRole;
    const targetFolderPath = currentFolderPath;
    setUploading(true);
    setDropFeedback('uploading');
    setDropMessage(`Uploading ${selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} files`} to ${uploadTargetLabel(targetRole, targetFolderPath)}`);
    try {
      let lastUploadedFile: StorageFile | null = null;
      for (const file of selectedFiles) {
        const payload = await uploadFile(targetRole, targetFolderPath, file);
        lastUploadedFile = payload.file;
        applyLocalCatalogDelta({ type: 'upsert_file', file: payload.file });
      }
      if (lastUploadedFile) setSelectedFile(lastUploadedFile);
      setError('');
      setDropFeedback('success');
      setDropMessage(`Uploaded ${selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} files`} to ${uploadTargetLabel(targetRole, targetFolderPath)}`);
      clearDropFeedbackLater();
      revalidateCatalog();
    } catch (err) {
      setDropFeedback('error');
      setDropMessage(err instanceof Error ? err.message : 'Upload failed.');
      clearDropFeedbackLater();
      throw err;
    } finally {
      setUploading(false);
    }
  }

  function handleAppDragEnter(event: DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragDepth((current) => current + 1);
    setDropFeedback(isDriveView || activeRole === 'all' ? 'blocked' : 'ready');
    setDropMessage(isDriveView
      ? 'Google Drive upload is not supported here yet.'
      : activeRole === 'all'
      ? 'Choose Generated or Uploaded before dropping files.'
      : `Drop to upload to ${uploadTargetLabel(activeRole, currentFolderPath)}`);
  }

  function handleAppDragOver(event: DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = isDriveView || activeRole === 'all' ? 'none' : 'copy';
  }

  function handleAppDragLeave(event: DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragDepth((current) => {
      const next = Math.max(0, current - 1);
      if (next === 0 && dropFeedback !== 'uploading') {
        setDropFeedback('idle');
        setDropMessage('');
      }
      return next;
    });
  }

  function handleAppDrop(event: DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragDepth(0);
    const droppedFiles = Array.from(event.dataTransfer.files || []);
    uploadSelectedFiles(droppedFiles).catch((err: Error) => setError(err.message));
  }

  function startDraggingSelection(selectionPayload: StorageSelectionDragPayload) {
    draggedSelectionRef.current = selectionPayload;
    setDraggingSelection({
      fileIds: new Set(selectedFiles.map((selected) => selected.id)),
      folderIds: new Set(selectedFolders.map((selected) => selected.id)),
    });
    setDraggedFile(null);
    setDraggedFolder(null);
  }

  function handleStorageFileDragStart(event: DragEvent<HTMLDivElement>, file: StorageFile) {
    if (isDriveItem(file)) {
      event.preventDefault();
      return 0;
    }
    const selectionPayload = selectedFileIds.has(file.id) && selectedItemCount > 1
      ? storageDragPayloadFromSelection(selectedMoveItems, storageAppId)
      : null;
    if (selectionPayload && storageSelectionItemCount(selectionPayload) > 0) {
      writeStorageSelectionDragData(event.dataTransfer, selectionPayload);
      startDraggingSelection(selectionPayload);
      return selectedItemCount;
    }
    writeStorageFileDragData(event.dataTransfer, storageDragPayloadFromFile(file, storageAppId));
    setDraggedFile(file);
    setDraggedFolder(null);
    setDraggingSelection(null);
    draggedSelectionRef.current = null;
    return 1;
  }

  function handleStorageFolderDragStart(event: DragEvent<HTMLElement>, folder: StorageFolder) {
    if (isDriveItem(folder) || !folder.relative_path) {
      event.preventDefault();
      return;
    }
    const selectionPayload = selectedFolderIds.has(folder.id) && selectedItemCount > 1
      ? storageDragPayloadFromSelection(selectedMoveItems, storageAppId)
      : null;
    if (selectionPayload && storageSelectionItemCount(selectionPayload) > 0) {
      attachStorageFolderDragImage(event, selectedItemCount);
      writeStorageSelectionDragData(event.dataTransfer, selectionPayload);
      startDraggingSelection(selectionPayload);
      return;
    }
    attachStorageFolderDragImage(event);
    writeStorageFolderDragData(event.dataTransfer, storageDragPayloadFromFolder(folder, storageAppId));
    setDraggedFolder(folder);
    setDraggedFile(null);
    setDraggingSelection(null);
    draggedSelectionRef.current = null;
  }

  function clearStorageDragState() {
    setDraggedFile(null);
    setDraggedFolder(null);
    setDraggingSelection(null);
    draggedSelectionRef.current = null;
  }

  function storageDropStatusForFolder(event: DragEvent<HTMLElement>, targetFolder: StorageFolder) {
    if (isDriveItem(targetFolder) || !isFileRole(targetFolder.role)) {
      return 'blocked';
    }
    const status = storageMoveDropStatus(event.dataTransfer, targetFolder.role);
    if (status !== 'ready') {
      return status;
    }
    const draggedSelectionReference = readStorageSelectionDragData(event.dataTransfer, storageAppId) || draggedSelectionRef.current;
    if (draggedSelectionReference && storageSelectionMoveTargetBlocked(draggedSelectionReference, targetFolder.role, targetFolder.relative_path)) {
      return 'blocked';
    }
    const draggedFolderReference = readStorageFolderDragData(event.dataTransfer, storageAppId) || draggedFolder;
    if (draggedFolderReference && folderMoveTargetBlocked(draggedFolderReference, targetFolder.role, targetFolder.relative_path)) {
      return 'blocked';
    }
    return status;
  }

  async function moveDroppedStorageSelection(selection: StorageSelectionDragPayload, targetFolderPath: string, targetRole: FileRole) {
    if (!storageSelectionItemCount(selection)) {
      setError('This Storage selection drag could not be read.');
      return;
    }
    if (storageSelectionMoveTargetBlocked(selection, targetRole, targetFolderPath)) {
      setError('Selected items can only be moved within their current storage section, and folders cannot move into themselves or child folders.');
      return;
    }
    const movePlan = storageDragSelectionMovePlan(selection);

    let nextSelectedFile: StorageFile | null = null;
    const selectedFileInsideMovedFolder = selectedFile
      ? movePlan.folders.some((folder) => selectedFile.role === folder.role && folderContainsPath(folder, selectedFile.relative_path))
      : false;
    const selectedFolderInsideMovedFolder = selectedFolder
      ? movePlan.folders.some((folder) => selectedFolder.role === folder.role && folderContainsPath(folder, selectedFolder.relative_path))
      : false;
    let nextCurrentFolderPath = currentFolderPath;
    let currentFolderMoved = false;

    const payload = await moveItemsReferences(movePlan.files, movePlan.folders, targetRole, targetFolderPath);
    for (const movedFile of payload.files) {
      applyLocalCatalogDelta({ type: 'upsert_file', file: movedFile.file, previous: movedFile.previous });
      if (fileMatchesReference(selectedFile, movedFile.previous)) {
        nextSelectedFile = movedFile.file;
      }
    }

    for (const movedFolder of payload.folders) {
      applyLocalCatalogDelta({ type: 'move_folder', previous: movedFolder.previous, folder: movedFolder.folder });
      if (activeRole === targetRole && folderContainsPath(movedFolder.previous, nextCurrentFolderPath)) {
        nextCurrentFolderPath = pathAfterFolderMove(nextCurrentFolderPath, movedFolder.previous.relative_path, movedFolder.folder.relative_path);
        currentFolderMoved = true;
      }
    }

    if (selectedFolderInsideMovedFolder) {
      setSelectedFolder(null);
      setFolderDetailsOpen(false);
    }
    if (selectedFileInsideMovedFolder && !nextSelectedFile) {
      setSelectedFile(null);
      setDetailsOpen(false);
      closePreviewModal();
    } else if (nextSelectedFile) {
      setSelectedFile(nextSelectedFile);
    }

    if (currentFolderMoved) {
      setCurrentFolderPathScoped(nextCurrentFolderPath);
      revalidateCatalog({ role: targetRole }, { folderPath: nextCurrentFolderPath, loading: 'foreground' });
    } else {
      revalidateCatalog();
    }
    clearSelectionMode();
    setError('');
  }

  async function moveDroppedStorageItem(event: DragEvent<HTMLElement>, targetFolderPath: string, targetRole: FileRole) {
    try {
      const draggedSelectionReference = readStorageSelectionDragData(event.dataTransfer, storageAppId) || draggedSelectionRef.current;
      if (draggedSelectionReference) {
        await moveDroppedStorageSelection(draggedSelectionReference, targetFolderPath, targetRole);
        return;
      }

      const draggedFileReference = readStorageFileDragData(event.dataTransfer, storageAppId)
        || (draggedFile ? storageDragPayloadFromFile(draggedFile, storageAppId) : null);
      if (draggedFileReference) {
        if (targetRole !== draggedFileReference.role) {
          setError('Files can only be moved within their current storage section.');
          return;
        }
        const payload = await moveFileReference(draggedFileReference, targetFolderPath);
        applyLocalCatalogDelta({ type: 'upsert_file', file: payload.file, previous: draggedFileReference });
        if (
          selectedFile?.id === draggedFileReference.file_id
          || selectedFile?.file_id === draggedFileReference.file_id
          || (selectedFile?.role === draggedFileReference.role && selectedFile.relative_path === draggedFileReference.relative_path)
        ) {
          setSelectedFile(payload.file);
        }
        setError('');
        revalidateCatalog();
        return;
      }

      const draggedFolderReference = readStorageFolderDragData(event.dataTransfer, storageAppId)
        || (draggedFolder ? storageDragPayloadFromFolder(draggedFolder, storageAppId) : null);
      if (!draggedFolderReference) {
        setError('Only Storage files or folders can be moved into folders.');
        return;
      }
      if (targetRole !== draggedFolderReference.role) {
        setError('Folders can only be moved within their current storage section.');
        return;
      }
      if (folderMoveTargetBlocked(draggedFolderReference, targetRole, targetFolderPath)) {
        setError('Folders cannot be moved into themselves or one of their child folders.');
        return;
      }
      const payload = await moveFolderReference(draggedFolderReference, targetFolderPath);
      applyLocalCatalogDelta({ type: 'move_folder', previous: draggedFolderReference, folder: payload.folder });
      const nextFolderPath = payload.folder.relative_path;
      if (selectedFolder?.role === draggedFolderReference.role && folderContainsPath(draggedFolderReference, selectedFolder.relative_path)) {
        setSelectedFolder(null);
        setFolderDetailsOpen(false);
      }
      if (selectedFile?.role === draggedFolderReference.role && normalizeFolderPath(selectedFile.relative_path).startsWith(`${normalizeFolderPath(draggedFolderReference.relative_path)}/`)) {
        setSelectedFile(null);
        setDetailsOpen(false);
        closePreviewModal();
      }
      if (activeRole === targetRole && folderContainsPath(draggedFolderReference, currentFolderPath)) {
        const movedCurrentFolderPath = pathAfterFolderMove(currentFolderPath, draggedFolderReference.relative_path, nextFolderPath);
        setCurrentFolderPathScoped(movedCurrentFolderPath);
        revalidateCatalog({ role: targetRole }, { folderPath: movedCurrentFolderPath, loading: 'foreground' });
      } else {
        revalidateCatalog();
      }
      setError('');
    } finally {
      clearStorageDragState();
    }
  }

  function requestFileDelete(file: StorageFile) {
    setError('');
    setPendingDelete({ kind: 'file', file });
  }

  function requestFolderDelete(folder: StorageFolder) {
    if (isDriveItem(folder)) {
      setError('Google Drive folder deletion is not supported here yet.');
      return;
    }
    if (!folder.relative_path) {
      setError('Storage root folders cannot be deleted.');
      return;
    }
    setError('');
    setPendingDelete({ kind: 'folder', folder });
  }

  async function removeFile(file: StorageFile) {
    if (isDriveItem(file)) {
      if (!itemCan(file, 'can_delete', false)) {
        setError('Google Drive did not grant delete permission for this file.');
        return;
      }
      await trashDriveFile(file);
      setFiles((current) => current.filter((item) => item.id !== file.id));
      filesRef.current = filesRef.current.filter((item) => item.id !== file.id);
      if (selectedFile?.id === file.id) {
        setSelectedFile(null);
        setDetailsOpen(false);
        closePreviewModal();
      }
      setError('');
      refresh(undefined, { loading: 'foreground' }).catch((err: Error) => setError(err.message));
      return;
    }
    if (!isFileRole(file.role)) {
      setError('This file is not a local Storage file.');
      return;
    }
    await deleteFile(file);
    applyLocalCatalogDelta({ type: 'delete_file', file });
    const parentPath = folderParentPath(file.relative_path);
    if (selectedFile?.id === file.id) {
      setSelectedFile(null);
      setDetailsOpen(false);
      closePreviewModal();
    }
    setCurrentFolderPathScoped(parentPath);
    pendingNavigationTargetRef.current = null;
    updateViewFilter({ query: '', role: file.role, kind: 'all' }, { folderPath: parentPath, preserveCustom: false });
  }

  async function removeFolder(folder: StorageFolder) {
    if (isDriveItem(folder)) {
      setError('Google Drive folder deletion is not supported here yet.');
      return;
    }
    if (!isFileRole(folder.role)) {
      setError('This folder is not a local Storage folder.');
      return;
    }
    const deletedPath = normalizeFolderPath(folder.relative_path);
    const parentPath = folderParentPath(deletedPath);
    await deleteFolder(folder);
    applyLocalCatalogDelta({ type: 'delete_folder', folder });
    if (selectedFolder?.id === folder.id) {
      setSelectedFolder(null);
      setFolderDetailsOpen(false);
    }
    if (activeRole === folder.role && folderContainsPath(folder, currentFolderPath)) {
      setCurrentFolderPathScoped(parentPath);
      revalidateCatalog({ role: folder.role }, { folderPath: parentPath, loading: 'foreground' });
    } else {
      revalidateCatalog();
    }
  }

  async function confirmPendingDelete() {
    if (!pendingDelete || deleteBusy) return;
    setDeleteBusy(true);
    try {
      if (pendingDelete.kind === 'folder') {
        await removeFolder(pendingDelete.folder);
      } else {
        await removeFile(pendingDelete.file);
      }
      setPendingDelete(null);
    } catch (err) {
      setPendingDelete(null);
      throw err;
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <main
      className="storage-shell"
      onDragEnter={handleAppDragEnter}
      onDragOver={handleAppDragOver}
      onDragLeave={handleAppDragLeave}
      onDrop={handleAppDrop}
    >
      {dropFeedback !== 'idle' || dragDepth > 0 ? (
        <div className={`drop-overlay ${dropFeedback}`} aria-live="polite">
          <div className="drop-overlay-panel">
            <Icon
              name={dropFeedback === 'success' ? 'check_circle' : dropFeedback === 'blocked' || dropFeedback === 'error' ? 'error' : dropFeedback === 'uploading' ? 'progress_activity' : 'upload_file'}
              className="drop-overlay-icon"
            />
            <strong>{dropFeedback === 'success' ? 'Upload complete' : dropFeedback === 'blocked' ? 'Storage role required' : dropFeedback === 'error' ? 'Upload failed' : dropFeedback === 'uploading' ? 'Uploading' : 'Drop files to upload'}</strong>
            <span>{dropMessage || `Upload to ${uploadTargetLabel(activeRole, currentFolderPath)}`}</span>
          </div>
        </div>
      ) : null}
      <section className="storage-workspace">
        <header className="storage-topbar">
          <label className="storage-search">
            <Icon name="search" />
            <input
              aria-label="Search in Storage"
              placeholder="Search in Storage"
              value={query}
              onChange={(event) => {
                if (isDriveView) {
                  setQuery(event.target.value);
                  queryRef.current = event.target.value;
                } else {
                  updateViewFilter({ query: event.target.value });
                }
              }}
            />
          </label>
          <div className="topbar-actions">
            {selectionMode ? (
              <div className="storage-selection-toolbar" aria-live="polite">
                <span className="storage-selection-count">{selectedItemCount} selected</span>
                <button aria-label="Clear selection" onClick={clearSelectionMode} title="Clear selection" type="button">
                  <Icon name="close" />
                </button>
              </div>
            ) : null}
            <CollectionViewToggle view={layoutMode} onChange={chooseLayoutMode} />
          </div>
        </header>

        <section className="content-panel">
          <div className="content-heading">
            {isInitialLoading ? (
              <>
                <div className="storage-breadcrumb storage-heading-skeleton" aria-hidden="true">
                  <span className="storage-app-skeleton__icon" />
                  <span className="storage-app-skeleton__line storage-app-skeleton__line--breadcrumb" />
                </div>
                <div className="content-counts storage-counts-skeleton" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
              </>
            ) : (
              <>
            <Breadcrumb className="storage-breadcrumb">
              <BreadcrumbList>
                <BreadcrumbItem>
                  {storageBreadcrumbLabel || folderBreadcrumbs.length ? (
                    <BreadcrumbLink asChild>
                      <button
                        type="button"
                        onClick={() => {
                          setDriveTarget(null);
                          driveTargetRef.current = null;
                          setCurrentFolderPathScoped('');
                          updateViewFilter({ query: '', role: 'all' }, { folderPath: '', preserveCustom: false });
                        }}
                        aria-label="Show Storage root"
                      >
                        <Home className="storage-breadcrumb-icon" />
                        Storage
                      </button>
                    </BreadcrumbLink>
                  ) : (
                    <BreadcrumbPage>
                      <Home className="storage-breadcrumb-icon" />
                      Storage
                    </BreadcrumbPage>
                  )}
                </BreadcrumbItem>
                {storageBreadcrumbLabel ? (
                  <>
                    <BreadcrumbSeparator />
                    <BreadcrumbItem>
                      {folderBreadcrumbs.length ? (
                        <BreadcrumbLink asChild>
                          <button
                            type="button"
                            onClick={() => {
                              const plan = breadcrumbRefreshPlan({ activeRole: activeRole as FileRole, folderPath: '', query, viewMode });
                              setCurrentFolderPathScoped(plan.folderPath);
                              if (plan.shouldWriteViewFilter) {
                                updateViewFilter(plan.filter, plan.viewFilterOptions);
                              } else {
                                refresh(plan.filter, { ...plan.refreshOptions, loading: 'foreground' }).catch((err: Error) => setError(err.message));
                              }
                            }}
                          >
                            {storageBreadcrumbLabel}
                          </button>
                        </BreadcrumbLink>
                      ) : (
                        <BreadcrumbPage>{storageBreadcrumbLabel}</BreadcrumbPage>
                      )}
                    </BreadcrumbItem>
                  </>
                ) : null}
                {folderBreadcrumbs.map((item, index) => {
                  const isCurrent = index === folderBreadcrumbs.length - 1;
                  return (
                    <Fragment key={item.path}>
                      <BreadcrumbSeparator />
                      <BreadcrumbItem>
                        {isCurrent ? (
                          <BreadcrumbPage>{item.label}</BreadcrumbPage>
                        ) : (
                          <BreadcrumbLink asChild>
                            <button
                              type="button"
                              onClick={() => {
                                const plan = breadcrumbRefreshPlan({ activeRole: activeRole as FileRole, folderPath: item.path, query, viewMode });
                                setCurrentFolderPathScoped(plan.folderPath);
                                if (plan.shouldWriteViewFilter) {
                                  updateViewFilter(plan.filter, plan.viewFilterOptions);
                                } else {
                                  refresh(plan.filter, { ...plan.refreshOptions, loading: 'foreground' }).catch((err: Error) => setError(err.message));
                                }
                              }}
                            >
                              {item.label}
                            </button>
                          </BreadcrumbLink>
                        )}
                      </BreadcrumbItem>
                    </Fragment>
                  );
                })}
              </BreadcrumbList>
            </Breadcrumb>
            {isCatalogTransitionLoading ? (
              <div className="content-counts storage-counts-skeleton" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            ) : (
              <div className="content-counts">
                <span>{visibleFolders.length} folders</span>
                <span>{fileCountLabel}</span>
                <span aria-label={`Folder size ${currentFolderSizeLabel}`} title="Folder size">{currentFolderSizeLabel}</span>
              </div>
            )}
              </>
            )}
          </div>

          {error ? (
            <div className="storage-error" role="status">
              <span>{error}</span>
              <button aria-label="Dismiss Storage error" onClick={() => setError('')} title="Dismiss" type="button">
                <Icon name="close" />
              </button>
            </div>
          ) : null}

          {viewMode === 'custom' ? (
            <section className="custom-view-bar" aria-label="Custom Storage view">
              <div>
                <Icon name="filter_list" />
                <strong>{customTitle || 'Custom file view'}</strong>
                <small>{filteredFiles.length} visible files from {customFileIds.length + customWorkspacePaths.length} selected references</small>
              </div>
              <button type="button" onClick={clearCustomFileView}>Clear custom view</button>
            </section>
          ) : null}

          <section className={`storage-browser ${layoutMode}`} aria-busy={isCatalogContentLoading} aria-label="Workspace storage">
            {isCatalogContentLoading ? (
              <StorageAppSkeleton view={layoutMode} />
            ) : null}
            {!isCatalogContentLoading ? visibleFolders.map((folder) => (
              <FolderCard
                canDelete={!isDriveItem(folder) && Boolean(folder.relative_path)}
                canDownload={!isDriveItem(folder)}
                dragging={draggedFolder?.id === folder.id || draggingFolderIds.has(folder.id)}
                key={folder.id}
                folder={folder}
                onDelete={() => requestFolderDelete(folder)}
                onDragEnd={clearStorageDragState}
                onDragStart={handleStorageFolderDragStart}
                onDownload={() => downloadFolderArchive(folder).catch((err: Error) => setError(err.message))}
                onLongPress={() => activateFolderSelection(folder)}
                onOpen={() => openFolder(folder)}
                onDropStatus={storageDropStatusForFolder}
                onDropStorageItem={(event, targetFolder) => {
                  if (!isFileRole(targetFolder.role)) {
                    setError('This folder is not a local Storage folder.');
                    return;
                  }
                  moveDroppedStorageItem(event, targetFolder.relative_path, targetFolder.role).catch((err: Error) => setError(err.message));
                }}
                onShowDetails={() => showFolderDetails(folder)}
                onToggleSelection={() => toggleFolderSelection(folder)}
                selected={selectedFolderIds.has(folder.id)}
                selectionMode={selectionMode}
              />
            )) : null}
            {!isCatalogContentLoading && filteredFiles.length ? (
              <AnimatedFileCollection
                draggingFileIds={draggingFileIds}
                files={filteredFiles}
                onDelete={requestFileDelete}
                onDownload={(file) => download(file).catch((err: Error) => setError(err.message))}
                onDragEnd={clearStorageDragState}
                onDragStart={handleStorageFileDragStart}
                onLongPress={activateFileSelection}
                onOpen={openFilePreview}
                onShowDetails={showFileDetails}
                onToggleSelection={toggleFileSelection}
                selectedFileId={selectedFile?.id}
                selectedFileIds={selectedFileIds}
                selectionMode={selectionMode}
                view={layoutMode}
              />
            ) : null}
            {catalogDisplayState === 'empty' ? (
              <div className="empty-state">{viewMode === 'custom' ? 'No files from this custom view are currently available.' : query.trim() ? 'No matching folders or files.' : 'No folders or files here yet.'}</div>
            ) : null}
            {!isCatalogContentLoading && catalogPagination?.has_more ? (
              <div className="catalog-page-actions">
                <button className="secondary-action" disabled={catalogLoadingMore} onClick={() => loadMoreFiles().catch((err: Error) => setError(err.message))} type="button">
                  {catalogLoadingMore ? 'Loading' : 'Load more'}
                </button>
              </div>
            ) : null}
          </section>
        </section>
      </section>

      {folderDetailsOpen && selectedFolder ? (
        <div className="details-modal-backdrop" onMouseDown={() => setFolderDetailsOpen(false)}>
          <section className="details-dialog" role="dialog" aria-modal="true" aria-labelledby="folder-details-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="file-details-header details-dialog-header">
              <div>
                <p className="storage-eyebrow">{isDriveItem(selectedFolder) ? 'Google Drive' : roleLabels[selectedFolder.role as FileRole]} · Folder</p>
                <h2 id="folder-details-dialog-title">{selectedFolder.name}</h2>
              </div>
              <button className="icon-button" onClick={() => setFolderDetailsOpen(false)} aria-label="Close folder details" type="button">
                <Icon name="close" />
              </button>
            </header>
            <section className="file-details-section">
              <h3>Details</h3>
              <dl>
                <div><dt>Path</dt><dd>{isDriveItem(selectedFolder) ? driveItemPath(selectedFolder) : selectedFolder.workspace_relative_path}</dd></div>
                <div><dt>Files</dt><dd>{selectedFolderStats?.fileCount ?? 0}</dd></div>
                <div><dt>Folders</dt><dd>{selectedFolderStats?.folderCount ?? 0}</dd></div>
                <div><dt>Size</dt><dd>{formatBytes(selectedFolderStats?.sizeBytes ?? 0)}</dd></div>
                <div><dt>Modified</dt><dd>{selectedFolder.modified_at ? new Date(selectedFolder.modified_at).toLocaleString() : 'Storage root'}</dd></div>
              </dl>
            </section>
          </section>
        </div>
      ) : null}

      {detailsOpen && selectedFile ? (
        <div className="details-modal-backdrop" onMouseDown={() => setDetailsOpen(false)}>
          <section className="details-dialog" role="dialog" aria-modal="true" aria-labelledby="details-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="file-details-header details-dialog-header">
              <div>
                <p className="storage-eyebrow">{isDriveItem(selectedFile) ? 'Google Drive' : roleLabels[selectedFile.role as FileRole]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2 id="details-dialog-title">{selectedFile.name}</h2>
              </div>
              <button className="icon-button" onClick={() => setDetailsOpen(false)} aria-label="Close details" type="button">
                <Icon name="close" />
              </button>
            </header>
            <section className="file-details-section">
              <h3>Details</h3>
              <dl>
                <div><dt>Path</dt><dd>{isDriveItem(selectedFile) ? driveItemPath(selectedFile) : selectedFile.workspace_relative_path}</dd></div>
                <div><dt>Size</dt><dd>{formatBytes(selectedFile.size_bytes)}</dd></div>
                <div><dt>Modified</dt><dd>{new Date(selectedFile.modified_at).toLocaleString()}</dd></div>
                <div><dt>Type</dt><dd>{selectedFile.content_type}</dd></div>
              </dl>
            </section>
            <section className="file-details-section">
              <h3>Rename</h3>
              <div className="rename-group">
                <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label="File name" />
                <button disabled={isDriveItem(selectedFile) && !itemCan(selectedFile, 'can_rename', false)} onClick={() => saveRename().catch((err: Error) => setError(err.message))}>Rename</button>
              </div>
            </section>
            {selectedFile.preview_kind === 'markdown' && !isDriveItem(selectedFile) ? (
              <section className="file-details-section markdown-actions">
                <h3>Markdown</h3>
                <button
                  className="secondary-action"
                  onClick={() => copyMarkdownContent().catch((err: Error) => setError(err.message))}
                  disabled={markdownCopying}
                  type="button"
                >
                  <Icon name={markdownCopied ? 'check' : 'content_copy'} />
                  {markdownCopied ? 'Copied' : 'Copy content'}
                </button>
                {markdownEditing ? (
                  <>
                    <div className="markdown-detail-editor">
                      <textarea
                        value={markdownDraft}
                        onChange={(event) => setMarkdownDraft(event.target.value)}
                        aria-label="Markdown source"
                        spellCheck
                      />
                    </div>
                    <button
                      className="secondary-action"
                      onClick={() => {
                        setMarkdownDraft(previewText);
                        setMarkdownEditing(false);
                      }}
                      type="button"
                    >
                      Cancel
                    </button>
                    <button className="primary-action" onClick={() => saveMarkdown().catch((err: Error) => setError(err.message))} disabled={markdownSaving} type="button">
                      <Icon name="save" />
                      {markdownSaving ? 'Saving' : 'Save'}
                    </button>
                  </>
                ) : (
                  <button className="secondary-action" onClick={() => setMarkdownEditing(true)} type="button">
                    <Icon name="edit" />
                    Edit Markdown
                  </button>
                )}
              </section>
            ) : null}
          </section>
        </div>
      ) : null}
      {pendingDelete ? (
        <div className="delete-confirmation-backdrop" onMouseDown={() => !deleteBusy && setPendingDelete(null)}>
          <section className="delete-confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-confirmation-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="delete-confirmation-icon" aria-hidden="true">
              <Icon name="delete" />
            </span>
            <div className="delete-confirmation-copy">
              <p className="storage-eyebrow">Permanent action</p>
              <h2 id="delete-confirmation-title">{pendingDeleteTitle}</h2>
              <strong>{pendingDeleteName}</strong>
              <span>{pendingDeletePath}</span>
              <p>{pendingDeleteDescription}</p>
            </div>
            <div className="delete-confirmation-actions">
              <button className="secondary-action" disabled={deleteBusy} onClick={() => setPendingDelete(null)} type="button" autoFocus>
                Cancel
              </button>
              <button className="primary-action" disabled={deleteBusy} onClick={() => confirmPendingDelete().catch((err: Error) => setError(err.message))} type="button">
                <Icon name="delete" />
                {deleteBusy ? 'Deleting' : pendingDeleteActionLabel}
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {previewModalOpen && selectedFile ? (
        <div className={previewBackdropClassName} onMouseDown={closePreviewModal}>
          <section className={previewModalClassName} ref={previewModalRef} style={previewModalStyle} role="dialog" aria-modal="true" aria-labelledby="preview-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="preview-modal-header" ref={previewHeaderRef}>
              <div>
                <p className="storage-eyebrow">{isDriveItem(selectedFile) ? 'Google Drive' : roleLabels[selectedFile.role as FileRole]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2 id="preview-modal-title">{selectedFile.name}</h2>
              </div>
              <div className="preview-modal-actions">
                <button className="icon-button preview-fullscreen-action" type="button" onClick={() => togglePreviewFullscreen().catch((err: Error) => setError(err.message))} aria-label={previewFullscreenLabel} aria-pressed={previewFullscreenActive} title={previewFullscreenLabel}>
                  <Icon name={previewFullscreenIcon} />
                </button>
                <button className="icon-button" type="button" onClick={() => showFileDetails(selectedFile)} aria-label="Show file details" title="Details">
                  <Icon name="info" />
                </button>
                <button className="icon-button" disabled={isDriveItem(selectedFile) && !itemCan(selectedFile, 'can_read', false)} type="button" onClick={() => download(selectedFile).catch((err: Error) => setError(err.message))} aria-label="Download file" title="Download">
                  <Icon name="download" />
                </button>
                <button className="icon-button danger" disabled={isDriveItem(selectedFile) && !itemCan(selectedFile, 'can_delete', false)} type="button" onClick={() => { exitPreviewFullscreenIfNeeded(); requestFileDelete(selectedFile); }} aria-label="Delete file" title="Delete">
                  <Icon name="delete" />
                </button>
                <button className="icon-button" type="button" onClick={closePreviewModal} aria-label="Close preview" title="Close">
                  <Icon name="close" />
                </button>
              </div>
            </header>
            <div className="preview-modal-body">
              <StoragePreview file={selectedFile} loading={previewLoading} previewUrl={previewUrl} previewText={previewText} previewTable={previewTable} />
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}

function StorageAppSkeleton({ view }: { view: CollectionViewMode }) {
  const folderCount = view === 'card' ? 2 : 3;
  const fileCount = view === 'card' ? 8 : 6;

  return (
    <>
      {Array.from({ length: folderCount }).map((_, index) => (
        <article className="folder-card storage-folder-skeleton" key={`folder-${index}`} aria-hidden="true">
          <span className="storage-app-skeleton__folder-main">
            <span className="storage-app-skeleton__icon" />
            <span className="storage-app-skeleton__line storage-app-skeleton__line--folder" />
          </span>
          <span className="storage-app-skeleton__folder-actions">
            <span />
            <span />
            <span />
          </span>
        </article>
      ))}
      <div
        className={`animated-file-collection is-${view} storage-app-skeleton__files`}
        role="status"
        aria-label="Storage files are loading"
      >
        {Array.from({ length: fileCount }).map((_, index) => (
          <article className={`animated-file-item is-${view} storage-file-skeleton`} key={`file-${index}`} aria-hidden="true">
            <span className="animated-file-preview-button storage-file-skeleton__preview">
              <span className="animated-file-preview" />
            </span>
            <span className={`animated-file-info is-${view}`}>
              <span className="animated-file-copy">
                <span className="storage-app-skeleton__line storage-app-skeleton__line--title" />
                <span className="storage-app-skeleton__line storage-app-skeleton__line--meta" />
              </span>
              <span className="animated-file-trailing storage-file-skeleton__trailing">
                <span className="storage-file-skeleton__actions">
                  <span />
                  <span />
                  <span />
                </span>
                <span className="storage-app-skeleton__line storage-app-skeleton__line--badge" />
              </span>
            </span>
          </article>
        ))}
      </div>
    </>
  );
}

async function readFullFileText(file: StorageFile) {
  const payload = await readFile(file, DOWNLOAD_BYTES);
  return decodeBase64(payload.content_base64, payload.file.content_type).text();
}

async function writeClipboardText(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back for browser contexts that block Clipboard API access.
    }
  }
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.setAttribute('readonly', 'true');
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  textArea.style.pointerEvents = 'none';
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(textArea);
  if (!copied) throw new Error('Unable to copy Markdown content.');
}

createRoot(document.getElementById('root')!).render(<App />);
