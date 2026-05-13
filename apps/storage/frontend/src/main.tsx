import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, DragEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { Home } from 'lucide-react';
import { AnimatedFileCollection, CollectionViewToggle, type CollectionViewMode } from './components/ui/animated-collection';
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from './components/ui/breadcramb';
import { CATALOG_PAGE_LIMIT, clearCustomView, decodeBase64, deleteFile, deleteFolder, downloadFolder, loadCatalog, loadViewFilter, moveFile, readFile, renameFile, setViewFilter, updateMarkdownFile, uploadFile } from './storageApi';
import { canInlinePreview, canTextPreview, StoragePreview } from './filePreview';
import { formatBytes, formatMegabytes, kindLabels, roleLabels } from './storageMeta';
import { Icon } from './Icon';
import { notifyActiveStorageFolderSelection, notifyActiveStorageSelection } from './lib/activeStorageSelection';
import { breadcrumbRefreshPlan, catalogLoadedCountAfterPage, catalogLoadedCountAfterRefresh, deleteFileWithCatalogRefresh, folderOpenRefreshPlan, resolvedFileNavigationPlan } from './lib/storageCatalogFlow';
import { fileFolderSelection, folderParentPath, folderStatsForSelection, normalizeFolderPath } from './lib/storageFolderLayer';
import { storageTargetFromParams, type StorageNavigationParams, type StorageNavigationTarget } from './lib/storageNavigationParams';
import { storageCustomScopedFiles, storageViewVisibleFiles, storageViewVisibleFolders } from './lib/storageSearch';
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

const viewKinds = new Set<PreviewKind | 'all'>(['all', 'image', 'video', 'audio', 'pdf', 'document', 'presentation', 'spreadsheet', 'markdown', 'text', 'file']);
const storageRootRoles: FileRole[] = ['uploaded', 'generated'];

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

function folderContainsPath(folder: StorageFolder, relativePath: string) {
  const folderPath = normalizeFolderPath(folder.relative_path);
  const childPath = normalizeFolderPath(relativePath);
  return !folderPath || childPath === folderPath || childPath.startsWith(`${folderPath}/`);
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

function FolderCard({ canDelete, folder, onDelete, onDownload, onDropFile, onOpen, onShowDetails }: {
  canDelete: boolean;
  folder: StorageFolder;
  onDelete: () => void;
  onDownload: () => void;
  onOpen: () => void;
  onDropFile: (folder: StorageFolder) => void;
  onShowDetails: () => void;
}) {
  return (
    <article
      className="folder-card"
      onDragOver={(event) => event.preventDefault()}
      onDrop={() => onDropFile(folder)}
    >
      <button className="folder-card-open" type="button" onClick={onOpen}>
        <Icon name="folder" className="folder-card-icon" />
        <span className="folder-card-main">
          <strong>{folder.name}</strong>
        </span>
      </button>
      <div className="folder-card-actions" aria-label={`Actions for ${folder.name}`}>
        <button className="animated-file-action folder-card-action" aria-label={`Show details for ${folder.name}`} onClick={onShowDetails} title="Details" type="button">
          <Icon name="info" />
        </button>
        <button className="animated-file-action folder-card-action" aria-label={`Download ${folder.name}`} onClick={onDownload} title="Download" type="button">
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

function App() {
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
  const [uploading, setUploading] = useState(false);
  const [dragDepth, setDragDepth] = useState(0);
  const [dropFeedback, setDropFeedback] = useState<DropFeedback>('idle');
  const [dropMessage, setDropMessage] = useState('');
  const [layoutMode, setLayoutMode] = useState<CollectionViewMode>(initialLayoutMode);
  const [viewMode, setViewMode] = useState<'search' | 'custom'>('search');
  const [customTitle, setCustomTitle] = useState('');
  const [customFileIds, setCustomFileIds] = useState<string[]>([]);
  const [customWorkspacePaths, setCustomWorkspacePaths] = useState<string[]>([]);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewTable, setPreviewTable] = useState<PreviewTablePayload | undefined>(undefined);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [previewImageSize, setPreviewImageSize] = useState<PreviewImageSize | null>(null);
  const [previewViewportSize, setPreviewViewportSize] = useState<PreviewImageSize>(() => ({ width: window.innerWidth, height: window.innerHeight }));
  const [previewHeaderHeight, setPreviewHeaderHeight] = useState(72);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<StorageFolder | null>(null);
  const [folderDetailsOpen, setFolderDetailsOpen] = useState(false);
  const [markdownEditing, setMarkdownEditing] = useState(false);
  const [markdownDraft, setMarkdownDraft] = useState('');
  const [markdownSaving, setMarkdownSaving] = useState(false);
  const [markdownCopying, setMarkdownCopying] = useState(false);
  const [markdownCopied, setMarkdownCopied] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [error, setError] = useState('');
  const viewFilterUpdatedAtRef = useRef('');
  const viewFilterWriteRef = useRef<number | null>(null);
  const viewFilterPendingRef = useRef(false);
  const markdownCopyTimerRef = useRef<number | null>(null);
  const dropFeedbackTimerRef = useRef<number | null>(null);
  const previewHeaderRef = useRef<HTMLElement | null>(null);
  const filesRef = useRef<StorageFile[]>([]);
  const catalogLoadedCountRef = useRef(0);
  const currentFolderPathRef = useRef('');
  const customFileIdsRef = useRef<string[]>([]);
  const customWorkspacePathsRef = useRef<string[]>([]);
  const queryRef = useRef('');
  const activeRoleRef = useRef<FileRole | 'all'>('all');
  const kindRef = useRef<PreviewKind | 'all'>('all');
  const viewModeRef = useRef<'search' | 'custom'>('search');
  const pendingNavigationTargetRef = useRef<StorageNavigationTarget | null>(storageTargetFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())));

  function setCurrentFolderPathScoped(path: string) {
    const normalizedPath = normalizeFolderPath(path);
    currentFolderPathRef.current = normalizedPath;
    setCurrentFolderPath(normalizedPath);
  }

  function applyRemoteViewFilter(filter: StorageViewFilter) {
    if (viewFilterPendingRef.current || filter.updated_at === viewFilterUpdatedAtRef.current) return;
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
  }

  function catalogRequest(
    filter?: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>,
    offset = 0,
    options: { fileIds?: string[]; folderPath?: string; viewMode?: StorageViewFilter['mode']; workspacePaths?: string[] } = {}
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
    options: { fileIds?: string[]; folderPath?: string; viewMode?: StorageViewFilter['mode']; workspacePaths?: string[] } = {}
  ) {
    let request = catalogRequest(filter, 0, options);
    let payload = await loadCatalog(request);
    let remoteFilter = normalizedViewFilter(payload.state.view_filter);
    if (remoteFilter.mode === 'custom' && !request.file_ids?.length && !request.workspace_relative_paths?.length) {
      request = catalogRequest(
        { query: remoteFilter.query, role: remoteFilter.role, kind: remoteFilter.kind },
        0,
        {
          fileIds: remoteFilter.file_ids,
          folderPath: options.folderPath,
          viewMode: remoteFilter.mode,
          workspacePaths: remoteFilter.workspace_relative_paths,
        }
      );
      payload = await loadCatalog(request);
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
      }
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
    applyRemoteViewFilter(normalizedViewFilter(payload.state.view_filter));
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
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
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'storage')) {
        handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'storage') {
        if (payload.resource === 'files') {
          refresh().catch((err: Error) => setError(err.message));
        }
        if (payload.resource === 'view-state') {
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
        setPreviewModalOpen(false);
        setDetailsOpen(false);
        setFolderDetailsOpen(false);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [detailsOpen, folderDetailsOpen, previewModalOpen]);

  function updateViewFilter(
    filter: Partial<Pick<StorageViewFilter, 'query' | 'role' | 'kind'>>,
    options: { folderPath?: string; preserveCustom?: boolean } = {}
  ) {
    const preserveCustom = options.preserveCustom ?? viewMode === 'custom';
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
      setViewFilter({ query: next.query, role: next.role, kind: next.kind, preserve_custom: preserveCustom })
        .then((payload) => {
          const remote = normalizedViewFilter(payload.state.view_filter);
          viewFilterUpdatedAtRef.current = remote.updated_at;
          return refresh(
            { query: remote.query, role: remote.role, kind: remote.kind },
            {
              fileIds: preserveCustom ? remote.file_ids : [],
              folderPath: options.folderPath,
              viewMode: preserveCustom ? remote.mode : 'search',
              workspacePaths: preserveCustom ? remote.workspace_relative_paths : [],
            }
          );
        })
        .catch((err: Error) => setError(err.message))
        .finally(() => {
          viewFilterPendingRef.current = false;
          viewFilterWriteRef.current = null;
        });
    }, 250);
  }

  async function focusResolvedNavigationFile(file: StorageFile) {
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

    const payload = await loadCatalog(catalogRequest(plan.filter, 0, plan.refreshOptions));
    const nextFiles = mergeUniqueFiles(payload.files, [file]);
    filesRef.current = nextFiles;
    catalogLoadedCountRef.current = catalogLoadedCountAfterRefresh(payload.files.length);
    setFiles(nextFiles);
    setFolders(payload.folders || []);
    setCatalogPagination(payload.pagination || null);
    focusFile(file, { persistFilter: true, preserveCustom: false, query: plan.filter.query });
  }

  function focusFile(file: StorageFile, options: { persistFilter?: boolean; preserveCustom?: boolean; query?: string } = {}) {
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
    if (target.targetType === 'folder') {
      const targetFolderPath = target.folderRelativePath || '';
      setCurrentFolderPathScoped(targetFolderPath);
      if (target.role) {
        updateViewFilter({ role: target.role }, { folderPath: targetFolderPath, preserveCustom: false });
      } else {
        refresh(undefined, { folderPath: targetFolderPath }).catch((err: Error) => setError(err.message));
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
    refresh().catch((err: Error) => setError(err.message));
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
    const plan = folderOpenRefreshPlan({
      activeRole,
      folderPath: folder.relative_path,
      folderRole: folder.role,
      viewMode,
    });
    setCurrentFolderPathScoped(plan.folderPath);
    if (plan.shouldWriteViewFilter) {
      updateViewFilter(plan.filter, plan.viewFilterOptions);
    } else {
      refresh(plan.filter, plan.refreshOptions).catch((err: Error) => setError(err.message));
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
    setSelectedFile(file);
    setDetailsOpen(false);
    setPreviewModalOpen(true);
  }

  function showFileDetails(file: StorageFile) {
    setSelectedFile(file);
    setPreviewModalOpen(false);
    setDetailsOpen(true);
    setFolderDetailsOpen(false);
  }

  function showFolderDetails(folder: StorageFolder) {
    setSelectedFolder(folder);
    setPreviewModalOpen(false);
    setDetailsOpen(false);
    setFolderDetailsOpen(true);
  }

  const customScopedFiles = useMemo(() => {
    return storageCustomScopedFiles({
      fileIds: customFileIds,
      files,
      viewMode,
      workspaceRelativePaths: customWorkspacePaths,
    });
  }, [customFileIds, customWorkspacePaths, files, viewMode]);

  const browsableFolders = useMemo(() => {
    const roots = storageRootRoles.map((role) => {
      return folders.find((folder) => folder.role === role && !folder.relative_path) || storageRootFolder(role);
    });
    return [
      ...roots,
      ...folders.filter((folder) => folder.relative_path)
    ];
  }, [folders]);

  const visibleFolders = useMemo(() => {
    return storageViewVisibleFolders({
      activeRole,
      browsableFolders,
      currentFolderPath,
      folders,
      query,
      viewMode,
    });
  }, [activeRole, browsableFolders, currentFolderPath, folders, query, viewMode]);

  const filteredFiles = useMemo(() => {
    return storageViewVisibleFiles({
      activeRole,
      currentFolderPath,
      files: customScopedFiles,
      kind,
      query,
      viewMode,
    });
  }, [activeRole, currentFolderPath, customScopedFiles, kind, query, viewMode]);
  const selectedFolderStats = useMemo(() => {
    return selectedFolder ? folderStatsForSelection({ role: selectedFolder.role, relativePath: selectedFolder.relative_path }, files, folders) : null;
  }, [files, folders, selectedFolder]);
  const currentFolderStats = useMemo(() => {
    return folderStatsForSelection({ role: activeRole, relativePath: activeRole === 'all' ? '' : currentFolderPath }, files, folders);
  }, [activeRole, currentFolderPath, files, folders]);
  const currentFolderSizeLabel = formatMegabytes(currentFolderStats.sizeBytes);
  const visibleFileTotal = catalogPagination?.total ?? filteredFiles.length;
  const fileCountLabel = visibleFileTotal > filteredFiles.length
    ? `${filteredFiles.length}/${visibleFileTotal} files`
    : `${filteredFiles.length} files`;
  const folderBreadcrumbs = folderBreadcrumbItems(currentFolderPath);
  const storageBreadcrumbLabel = activeRole === 'all' ? '' : roleLabels[activeRole];

  useEffect(() => {
    setPreviewText('');
    setPreviewUrl('');
    setPreviewTable(undefined);
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
      setPreviewModalOpen(false);
      setDetailsOpen(false);
      return;
    }
  }, [selectedFile]);

  useEffect(() => {
    if (!previewModalOpen) return;
    function updatePreviewViewportSize() {
      setPreviewViewportSize({ width: window.innerWidth, height: window.innerHeight });
    }
    updatePreviewViewportSize();
    window.addEventListener('resize', updatePreviewViewportSize);
    window.addEventListener('orientationchange', updatePreviewViewportSize);
    return () => {
      window.removeEventListener('resize', updatePreviewViewportSize);
      window.removeEventListener('orientationchange', updatePreviewViewportSize);
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
    loadFullPreview(selectedFile)
      .then((payload) => {
        if (!active) return;
        setPreviewText(payload.text);
        setMarkdownDraft(payload.text);
        setPreviewUrl(payload.url);
        setPreviewTable(payload.table);
      })
      .catch((err: Error) => active && setError(err.message));
    return () => {
      active = false;
    };
  }, [markdownEditing, previewModalOpen, selectedFile]);

  const previewImageLayout = useMemo(() => {
    if (!previewModalOpen || selectedFile?.preview_kind !== 'image' || !previewImageSize) return null;
    return fittedPreviewImageSize(previewImageSize, previewViewportSize, previewHeaderHeight);
  }, [previewHeaderHeight, previewImageSize, previewModalOpen, previewViewportSize, selectedFile?.preview_kind]);

  const previewModalStyle: PreviewImageStyle | undefined = previewImageLayout
    ? {
      width: `${previewImageLayout.width}px`,
      '--preview-image-height': `${previewImageLayout.height}px`
    }
    : undefined;

  async function download(file: StorageFile) {
    const payload = await readFile(file, DOWNLOAD_BYTES);
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
    const payload = await renameFile(selectedFile, renameValue);
    await refresh();
    setSelectedFile(payload.file);
  }

  async function saveMarkdown() {
    if (!selectedFile || selectedFile.preview_kind !== 'markdown') return;
    setMarkdownSaving(true);
    try {
      const payload = await updateMarkdownFile(selectedFile, markdownDraft);
      await refresh();
      setSelectedFile(payload.file);
      setPreviewText(markdownDraft);
      setMarkdownEditing(false);
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
      }
      await refresh();
      if (lastUploadedFile) setSelectedFile(lastUploadedFile);
      setError('');
      setDropFeedback('success');
      setDropMessage(`Uploaded ${selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} files`} to ${uploadTargetLabel(targetRole, targetFolderPath)}`);
      clearDropFeedbackLater();
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
    setDropFeedback(activeRole === 'all' ? 'blocked' : 'ready');
    setDropMessage(activeRole === 'all'
      ? 'Choose Generated or Uploaded before dropping files.'
      : `Drop to upload to ${uploadTargetLabel(activeRole, currentFolderPath)}`);
  }

  function handleAppDragOver(event: DragEvent<HTMLElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = activeRole === 'all' ? 'none' : 'copy';
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

  async function moveDraggedFile(targetFolderPath: string, targetRole?: FileRole) {
    if (!draggedFile) return;
    if (targetRole && targetRole !== draggedFile.role) {
      setError('Files can only be moved within their current storage section.');
      setDraggedFile(null);
      return;
    }
    const payload = await moveFile(draggedFile, targetFolderPath);
    await refresh();
    if (selectedFile?.id === draggedFile.id) setSelectedFile(payload.file);
    setDraggedFile(null);
  }

  async function removeFile(file: StorageFile) {
    if (!window.confirm(`Delete ${file.name}? This removes the file from workspace storage.`)) return;
    await deleteFileWithCatalogRefresh(file, {
      clearSelectedFile: (fileId) => {
        if (selectedFile?.id === fileId) setSelectedFile(null);
      },
      deleteFile,
      refresh,
    });
  }

  async function removeFolder(folder: StorageFolder) {
    if (!folder.relative_path) {
      setError('Storage root folders cannot be deleted.');
      return;
    }
    if (!window.confirm(`Delete ${folder.name}? This removes the folder and every file inside it from workspace storage.`)) return;
    const deletedPath = normalizeFolderPath(folder.relative_path);
    const parentPath = folderParentPath(deletedPath);
    await deleteFolder(folder);
    if (selectedFolder?.id === folder.id) {
      setSelectedFolder(null);
      setFolderDetailsOpen(false);
    }
    if (activeRole === folder.role && folderContainsPath(folder, currentFolderPath)) {
      setCurrentFolderPathScoped(parentPath);
      await refresh({ role: folder.role }, { folderPath: parentPath });
    } else {
      await refresh();
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
            <input aria-label="Search in Storage" placeholder="Search in Storage" value={query} onChange={(event) => updateViewFilter({ query: event.target.value })} />
          </label>
          <div className="topbar-actions">
            <CollectionViewToggle view={layoutMode} onChange={chooseLayoutMode} />
          </div>
        </header>

        <section className="content-panel">
          <div className="content-heading">
            <Breadcrumb className="storage-breadcrumb">
              <BreadcrumbList>
                <BreadcrumbItem>
                  {storageBreadcrumbLabel || folderBreadcrumbs.length ? (
                    <BreadcrumbLink asChild>
                      <button
                        type="button"
                        onClick={() => {
                          setCurrentFolderPathScoped('');
                          updateViewFilter({ role: 'all' }, { folderPath: '', preserveCustom: false });
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
                              const plan = breadcrumbRefreshPlan({ activeRole: activeRole as FileRole, folderPath: '', viewMode });
                              setCurrentFolderPathScoped(plan.folderPath);
                              if (plan.shouldWriteViewFilter) {
                                updateViewFilter(plan.filter, plan.viewFilterOptions);
                              } else {
                                refresh(plan.filter, plan.refreshOptions).catch((err: Error) => setError(err.message));
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
                                const plan = breadcrumbRefreshPlan({ activeRole: activeRole as FileRole, folderPath: item.path, viewMode });
                                setCurrentFolderPathScoped(plan.folderPath);
                                if (plan.shouldWriteViewFilter) {
                                  updateViewFilter(plan.filter, plan.viewFilterOptions);
                                } else {
                                  refresh(plan.filter, plan.refreshOptions).catch((err: Error) => setError(err.message));
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
            <div className="content-counts">
              <span>{visibleFolders.length} folders</span>
              <span>{fileCountLabel}</span>
              <span aria-label={`Folder size ${currentFolderSizeLabel}`} title="Folder size">{currentFolderSizeLabel}</span>
            </div>
          </div>

          {error ? <div className="storage-error">{error}</div> : null}

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

          <section className={`storage-browser ${layoutMode}`} aria-label="Workspace storage">
            {visibleFolders.map((folder) => (
              <FolderCard
                canDelete={Boolean(folder.relative_path)}
                key={folder.id}
                folder={folder}
                onDelete={() => removeFolder(folder).catch((err: Error) => setError(err.message))}
                onDownload={() => downloadFolderArchive(folder).catch((err: Error) => setError(err.message))}
                onOpen={() => openFolder(folder)}
                onDropFile={(targetFolder) => moveDraggedFile(targetFolder.relative_path, targetFolder.role).catch((err: Error) => setError(err.message))}
                onShowDetails={() => showFolderDetails(folder)}
              />
            ))}
            {filteredFiles.length ? (
              <AnimatedFileCollection
                files={filteredFiles}
                onDelete={(file) => removeFile(file).catch((err: Error) => setError(err.message))}
                onDownload={(file) => download(file).catch((err: Error) => setError(err.message))}
                onDragEnd={() => setDraggedFile(null)}
                onDragStart={(file) => setDraggedFile(file)}
                onOpen={openFilePreview}
                onShowDetails={showFileDetails}
                selectedFileId={selectedFile?.id}
                view={layoutMode}
              />
            ) : null}
            {!filteredFiles.length && !visibleFolders.length ? (
              <div className="empty-state">{viewMode === 'custom' ? 'No files from this custom view are currently available.' : query.trim() ? 'No matching folders or files.' : 'No folders or files here yet.'}</div>
            ) : null}
            {catalogPagination?.has_more ? (
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
                <p className="storage-eyebrow">{roleLabels[selectedFolder.role]} · Folder</p>
                <h2 id="folder-details-dialog-title">{selectedFolder.name}</h2>
              </div>
              <button className="icon-button" onClick={() => setFolderDetailsOpen(false)} aria-label="Close folder details" type="button">
                <Icon name="close" />
              </button>
            </header>
            <section className="file-details-section">
              <h3>Details</h3>
              <dl>
                <div><dt>Path</dt><dd>{selectedFolder.workspace_relative_path}</dd></div>
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
                <p className="storage-eyebrow">{roleLabels[selectedFile.role]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2 id="details-dialog-title">{selectedFile.name}</h2>
              </div>
              <button className="icon-button" onClick={() => setDetailsOpen(false)} aria-label="Close details" type="button">
                <Icon name="close" />
              </button>
            </header>
            <section className="file-details-section">
              <h3>Details</h3>
              <dl>
                <div><dt>Path</dt><dd>{selectedFile.workspace_relative_path}</dd></div>
                <div><dt>Size</dt><dd>{formatBytes(selectedFile.size_bytes)}</dd></div>
                <div><dt>Modified</dt><dd>{new Date(selectedFile.modified_at).toLocaleString()}</dd></div>
                <div><dt>Type</dt><dd>{selectedFile.content_type}</dd></div>
              </dl>
            </section>
            <section className="file-details-section">
              <h3>Rename</h3>
              <div className="rename-group">
                <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label="File name" />
                <button onClick={() => saveRename().catch((err: Error) => setError(err.message))}>Rename</button>
              </div>
            </section>
            {selectedFile.preview_kind === 'markdown' ? (
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
      {previewModalOpen && selectedFile ? (
        <div className="preview-modal-backdrop" onMouseDown={() => setPreviewModalOpen(false)}>
          <section className={previewImageLayout ? 'preview-modal image-preview' : 'preview-modal'} style={previewModalStyle} role="dialog" aria-modal="true" aria-labelledby="preview-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="preview-modal-header" ref={previewHeaderRef}>
              <div>
                <p className="storage-eyebrow">{roleLabels[selectedFile.role]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2 id="preview-modal-title">{selectedFile.name}</h2>
              </div>
              <div className="preview-modal-actions">
                <button className="icon-button" type="button" onClick={() => showFileDetails(selectedFile)} aria-label="Show file details" title="Details">
                  <Icon name="info" />
                </button>
                <button className="icon-button" type="button" onClick={() => download(selectedFile).catch((err: Error) => setError(err.message))} aria-label="Download file" title="Download">
                  <Icon name="download" />
                </button>
                <button className="icon-button danger" type="button" onClick={() => removeFile(selectedFile).catch((err: Error) => setError(err.message))} aria-label="Delete file" title="Delete">
                  <Icon name="delete" />
                </button>
                <button className="icon-button" type="button" onClick={() => setPreviewModalOpen(false)} aria-label="Close preview" title="Close">
                  <Icon name="close" />
                </button>
              </div>
            </header>
            <div className="preview-modal-body">
              <StoragePreview file={selectedFile} previewUrl={previewUrl} previewText={previewText} previewTable={previewTable} />
            </div>
          </section>
        </div>
      ) : null}
    </main>
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
