import { useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { clearCustomView, createFolder, decodeBase64, deleteFile, loadCatalog, loadViewFilter, moveFile, readFile, renameFile, setViewFilter, updateMarkdownFile, uploadFile } from './galleryApi';
import { canInlinePreview, canTextPreview, FileCardPreview, GalleryPreview } from './filePreview';
import { formatBytes, iconForKind, kindLabels, roleLabels } from './galleryMeta';
import { Icon } from './Icon';
import { notifyActiveGallerySelection } from './lib/activeGallerySelection';
import { galleryTargetFromParams, type GalleryNavigationParams, type GalleryNavigationTarget } from './lib/galleryNavigationParams';
import { MarkdownPreview } from './markdownPreview';
import { loadFullPreview } from './previewCache';
import type { FileRole, GalleryFile, GalleryFolder, GalleryViewFilter, PreviewKind, PreviewTablePayload } from './types';
import './styles/main.css';

const DOWNLOAD_BYTES = 100 * 1024 * 1024;
const VIEW_SYNC_MS = 2000;
const LAYOUT_STORAGE_KEY = 'gallery.layout-mode';

type DropFeedback = 'idle' | 'ready' | 'blocked' | 'uploading' | 'success' | 'error';

const viewKinds = new Set<PreviewKind | 'all'>(['all', 'image', 'video', 'audio', 'pdf', 'document', 'presentation', 'spreadsheet', 'markdown', 'text', 'file']);
const uploadBucketPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const kindFilterOptions: Array<{ kind: PreviewKind | 'all'; label: string }> = [
  { kind: 'all', label: 'All types' },
  { kind: 'image', label: 'Images' },
  { kind: 'video', label: 'Videos' },
  { kind: 'audio', label: 'Audio' },
  { kind: 'pdf', label: 'PDFs' },
  { kind: 'document', label: 'Documents' },
  { kind: 'presentation', label: 'Presentations' },
  { kind: 'spreadsheet', label: 'Spreadsheets' },
  { kind: 'markdown', label: 'Markdown' },
  { kind: 'text', label: 'Text' },
  { kind: 'file', label: 'Other files' }
];

function normalizedViewFilter(filter?: Partial<GalleryViewFilter>): GalleryViewFilter {
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

function FileCard({ file, selected, onOpen, onDownload, onDelete, onDragStart, onDragEnd }: {
  file: GalleryFile;
  selected: boolean;
  onOpen: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  return (
    <article className={selected ? 'gallery-card selected' : 'gallery-card'} draggable onDragStart={onDragStart} onDragEnd={onDragEnd}>
      <button className="gallery-card-open" onClick={onOpen} type="button">
        <div className="gallery-card-preview">
          <FileCardPreview file={file} />
        </div>
        <span className="gallery-card-main">
          <strong>{file.name}</strong>
          <span>{kindLabels[file.preview_kind]} · {formatBytes(file.size_bytes)}</span>
        </span>
        <span className="gallery-card-path">{file.workspace_relative_path}</span>
      </button>
      <span className="gallery-card-role">{roleLabels[file.role]}</span>
      <span className="gallery-card-actions">
        <button className="card-action" aria-label={`Download ${file.name}`} onClick={onDownload} type="button">
          <Icon name="download" />
        </button>
        <button className="card-action danger" aria-label={`Delete ${file.name}`} onClick={onDelete} type="button">
          <Icon name="delete" />
        </button>
      </span>
    </article>
  );
}

function parentFolderPath(relativePath: string) {
  const parts = relativePath.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

function visibleFileParentPath(file: GalleryFile) {
  const parts = file.relative_path.split('/').filter(Boolean);
  if (file.role === 'uploaded' && parts.length === 2 && uploadBucketPattern.test(parts[0])) return '';
  return parentFolderPath(file.relative_path);
}

function fileFromNavigationTarget(files: GalleryFile[], target: GalleryNavigationTarget | null) {
  if (!target) return null;
  return files.find((file) => {
    if (target.fileId && file.id === target.fileId) return true;
    return Boolean(target.workspaceRelativePath && file.workspace_relative_path === target.workspaceRelativePath);
  }) || null;
}

function breadcrumbItems(currentFolderPath: string) {
  const parts = currentFolderPath.split('/').filter(Boolean);
  return [
    { label: 'Storage root', path: '' },
    ...parts.map((part, index) => ({ label: part, path: parts.slice(0, index + 1).join('/') }))
  ];
}

function hasDraggedFiles(dataTransfer: DataTransfer) {
  if (Array.from(dataTransfer.types || []).includes('Files')) return true;
  return Array.from(dataTransfer.items || []).some((item) => item.kind === 'file');
}

function uploadTargetLabel(role: FileRole | 'all', folderPath: string) {
  if (role === 'all') return 'Choose Generated or Uploaded first';
  return `${roleLabels[role]}${folderPath ? ` / ${folderPath}` : ''}`;
}

function FolderCard({ folder, onOpen, onDropFile }: {
  folder: GalleryFolder;
  onOpen: () => void;
  onDropFile: (folder: GalleryFolder) => void;
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
          <small>{roleLabels[folder.role]}</small>
        </span>
      </button>
    </article>
  );
}

function DetailFolderRow({ folder, onOpen, onDropFile }: {
  folder: GalleryFolder;
  onOpen: () => void;
  onDropFile: (folder: GalleryFolder) => void;
}) {
  return (
    <div
      className="details-row folder-row"
      role="row"
      onDragOver={(event) => event.preventDefault()}
      onDrop={() => onDropFile(folder)}
    >
      <div className="details-name-cell" role="cell">
        <button className="details-name-button" type="button" onClick={onOpen}>
          <Icon name="folder" />
          <span>{folder.name}</span>
        </button>
      </div>
      <span role="cell">Folder</span>
      <span role="cell">{roleLabels[folder.role]}</span>
      <span role="cell">-</span>
      <span role="cell">{new Date(folder.modified_at).toLocaleString()}</span>
      <span className="details-actions-cell" role="cell" />
    </div>
  );
}

function DetailFileRow({ file, selected, onOpen, onDownload, onDelete, onDragStart, onDragEnd }: {
  file: GalleryFile;
  selected: boolean;
  onOpen: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  return (
    <div className={selected ? 'details-row file-row selected' : 'details-row file-row'} role="row" draggable onDragStart={onDragStart} onDragEnd={onDragEnd}>
      <div className="details-name-cell" role="cell">
        <button className="details-name-button" type="button" onClick={onOpen}>
          <Icon name={file.preview_kind === 'spreadsheet' ? 'table' : 'draft'} />
          <span>{file.name}</span>
        </button>
      </div>
      <span role="cell">{kindLabels[file.preview_kind]}</span>
      <span role="cell">{roleLabels[file.role]}</span>
      <span role="cell">{formatBytes(file.size_bytes)}</span>
      <span role="cell">{new Date(file.modified_at).toLocaleString()}</span>
      <span className="details-actions-cell" role="cell">
        <button className="card-action" aria-label={`Download ${file.name}`} onClick={onDownload} type="button"><Icon name="download" /></button>
        <button className="card-action danger" aria-label={`Delete ${file.name}`} onClick={onDelete} type="button"><Icon name="delete" /></button>
      </span>
    </div>
  );
}

function App() {
  const [files, setFiles] = useState<GalleryFile[]>([]);
  const [folders, setFolders] = useState<GalleryFolder[]>([]);
  const [selectedFile, setSelectedFile] = useState<GalleryFile | null>(null);
  const [activeRole, setActiveRole] = useState<FileRole | 'all'>('all');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [currentFolderPath, setCurrentFolderPath] = useState('');
  const [newFolderName, setNewFolderName] = useState('');
  const [draggedFile, setDraggedFile] = useState<GalleryFile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragDepth, setDragDepth] = useState(0);
  const [dropFeedback, setDropFeedback] = useState<DropFeedback>('idle');
  const [dropMessage, setDropMessage] = useState('');
  const [layoutMode, setLayoutMode] = useState<'cards' | 'details'>(() => window.localStorage.getItem(LAYOUT_STORAGE_KEY) === 'details' ? 'details' : 'cards');
  const [viewMode, setViewMode] = useState<'search' | 'custom'>('search');
  const [customTitle, setCustomTitle] = useState('');
  const [customFileIds, setCustomFileIds] = useState<string[]>([]);
  const [customWorkspacePaths, setCustomWorkspacePaths] = useState<string[]>([]);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewTable, setPreviewTable] = useState<PreviewTablePayload | undefined>(undefined);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
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
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const dropFeedbackTimerRef = useRef<number | null>(null);
  const filesRef = useRef<GalleryFile[]>([]);
  const queryRef = useRef('');
  const viewModeRef = useRef<'search' | 'custom'>('search');
  const pendingNavigationTargetRef = useRef<GalleryNavigationTarget | null>(galleryTargetFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())));

  function applyRemoteViewFilter(filter: GalleryViewFilter) {
    if (viewFilterPendingRef.current || filter.updated_at === viewFilterUpdatedAtRef.current) return;
    viewFilterUpdatedAtRef.current = filter.updated_at;
    setViewMode(filter.mode);
    setCustomTitle(filter.title);
    setCustomFileIds(filter.file_ids);
    setCustomWorkspacePaths(filter.workspace_relative_paths);
    setQuery(filter.query);
    setActiveRole(filter.role);
    setKind(filter.kind);
  }

  async function refresh() {
    const payload = await loadCatalog();
    filesRef.current = payload.files;
    setFiles(payload.files);
    setFolders(payload.folders || []);
    applyRemoteViewFilter(normalizedViewFilter(payload.state.view_filter));
    const pendingFile = fileFromNavigationTarget(payload.files, pendingNavigationTargetRef.current);
    if (pendingFile) {
      focusFile(pendingFile, { persistFilter: true });
      pendingNavigationTargetRef.current = null;
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
    viewModeRef.current = viewMode;
  }, [viewMode]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'gallery' }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: GalleryNavigationParams;
        resource?: string;
        type?: string;
      };
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'gallery')) {
        handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'gallery') {
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
      notifyActiveGallerySelection(selectedFile);
    }
  }, [selectedFile]);

  useEffect(() => {
    if (!previewModalOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setPreviewModalOpen(false);
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [previewModalOpen]);

  function updateViewFilter(filter: Partial<Pick<GalleryViewFilter, 'query' | 'role' | 'kind'>>) {
    const next = normalizedViewFilter({ query, role: activeRole, kind: kind as PreviewKind | 'all', ...filter });
    setQuery(next.query);
    setActiveRole(next.role);
    setKind(next.kind);
    viewFilterPendingRef.current = true;
    if (viewFilterWriteRef.current !== null) window.clearTimeout(viewFilterWriteRef.current);
    viewFilterWriteRef.current = window.setTimeout(() => {
      setViewFilter({ query: next.query, role: next.role, kind: next.kind, preserve_custom: viewMode === 'custom' })
        .then((payload) => {
          const remote = normalizedViewFilter(payload.state.view_filter);
          viewFilterUpdatedAtRef.current = remote.updated_at;
        })
        .catch((err: Error) => setError(err.message))
        .finally(() => {
          viewFilterPendingRef.current = false;
          viewFilterWriteRef.current = null;
        });
    }, 250);
  }

  function focusFile(file: GalleryFile, options: { persistFilter?: boolean } = {}) {
    setSelectedFile(file);
    setCurrentFolderPath(visibleFileParentPath(file));
    setActiveRole(file.role);
    setKind('all');
    if (options.persistFilter) {
      viewFilterPendingRef.current = true;
      if (viewFilterWriteRef.current !== null) window.clearTimeout(viewFilterWriteRef.current);
      setViewFilter({
        query: queryRef.current,
        role: file.role,
        kind: 'all',
        preserve_custom: viewModeRef.current === 'custom'
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

  function handleNavigationParams(params: GalleryNavigationParams) {
    const target = galleryTargetFromParams(params);
    if (!target) {
      return;
    }
    pendingNavigationTargetRef.current = target;
    const file = fileFromNavigationTarget(filesRef.current, target);
    if (file) {
      focusFile(file, { persistFilter: true });
      pendingNavigationTargetRef.current = null;
      return;
    }
    refresh().catch((err: Error) => setError(err.message));
  }

  function clearCustomFileView() {
    clearCustomView()
      .then((payload) => applyRemoteViewFilter(normalizedViewFilter(payload.state.view_filter)))
      .catch((err: Error) => setError(err.message));
  }

  function chooseLayoutMode(nextMode: 'cards' | 'details') {
    setLayoutMode(nextMode);
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, nextMode);
  }

  function openFolder(folder: GalleryFolder) {
    setCurrentFolderPath(folder.relative_path);
    if (activeRole !== folder.role) updateViewFilter({ role: folder.role });
  }

  function clearDropFeedbackLater() {
    if (dropFeedbackTimerRef.current !== null) window.clearTimeout(dropFeedbackTimerRef.current);
    dropFeedbackTimerRef.current = window.setTimeout(() => {
      setDropFeedback('idle');
      setDropMessage('');
      dropFeedbackTimerRef.current = null;
    }, 1400);
  }

  const customScopedFiles = useMemo(() => {
    const customIds = new Set(customFileIds);
    const customPaths = new Set(customWorkspacePaths);
    if (viewMode !== 'custom') return files;
    return files.filter((file) => customIds.has(file.id) || customPaths.has(file.workspace_relative_path));
  }, [customFileIds, customWorkspacePaths, files, viewMode]);

  const visibleFolders = useMemo(() => {
    if (viewMode === 'custom') return [];
    const needle = query.trim().toLowerCase();
    return folders.filter((folder) => {
      const roleMatch = activeRole === 'all' || folder.role === activeRole;
      const parentMatch = parentFolderPath(folder.relative_path) === currentFolderPath;
      const textMatch = !needle || `${folder.name} ${folder.workspace_relative_path}`.toLowerCase().includes(needle);
      return roleMatch && parentMatch && textMatch;
    });
  }, [activeRole, currentFolderPath, folders, query, viewMode]);

  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const folderScopedFiles = viewMode === 'custom'
      ? customScopedFiles
      : customScopedFiles.filter((file) => visibleFileParentPath(file) === currentFolderPath);
    return folderScopedFiles.filter((file) => {
      const roleMatch = activeRole === 'all' || file.role === activeRole;
      const kindMatch = kind === 'all' || file.preview_kind === kind;
      const textMatch = !needle || `${file.name} ${file.workspace_relative_path} ${file.content_type}`.toLowerCase().includes(needle);
      return roleMatch && kindMatch && textMatch;
    });
  }, [activeRole, currentFolderPath, customScopedFiles, kind, query, viewMode]);

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
    setPreviewModalOpen(false);
    if (!selectedFile || (!canInlinePreview(selectedFile) && !canTextPreview(selectedFile))) return;
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
  }, [selectedFile]);

  async function download(file: GalleryFile) {
    const payload = await readFile(file, DOWNLOAD_BYTES);
    const url = URL.createObjectURL(decodeBase64(payload.content_base64, payload.file.content_type));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = payload.file.name;
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

  async function createCurrentFolder() {
    const folderName = newFolderName.trim();
    if (!folderName) return false;
    if (activeRole === 'all') {
      setError('Choose Generated or Uploaded before creating a folder.');
      return false;
    }
    const payload = await createFolder(activeRole, currentFolderPath, folderName);
    await refresh();
    setNewFolderName('');
    setCurrentFolderPath(payload.folder.relative_path);
    return true;
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
      let lastUploadedFile: GalleryFile | null = null;
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

  function requestUpload() {
    if (activeRole === 'all') {
      setError('Choose Generated or Uploaded before uploading a file.');
      return;
    }
    uploadInputRef.current?.click();
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

  async function removeFile(file: GalleryFile) {
    if (!window.confirm(`Delete ${file.name}? This removes the file from workspace storage.`)) return;
    await deleteFile(file);
    setFiles((current) => current.filter((item) => item.id !== file.id));
    if (selectedFile?.id === file.id) setSelectedFile(null);
  }

  return (
    <main
      className="gallery-shell"
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
      <section className="gallery-workspace">
        <header className="gallery-topbar">
          <label className="gallery-search">
            <Icon name="search" />
            <input placeholder="Search in Gallery" value={query} onChange={(event) => updateViewFilter({ query: event.target.value })} />
          </label>
          <div className="gallery-filter-strip">
            <div className="storage-segmented" aria-label="Storage section">
              <button className={activeRole === 'all' ? 'selected' : ''} type="button" onClick={() => updateViewFilter({ role: 'all' })}>All</button>
              <button className={activeRole === 'uploaded' ? 'selected' : ''} type="button" onClick={() => updateViewFilter({ role: 'uploaded' })}>Uploaded</button>
              <button className={activeRole === 'generated' ? 'selected' : ''} type="button" onClick={() => updateViewFilter({ role: 'generated' })}>Generated</button>
            </div>
            <label className="kind-filter-select">
              <span>Type</span>
              <select value={kind} onChange={(event) => updateViewFilter({ kind: event.target.value as PreviewKind | 'all' })}>
                {kindFilterOptions.map((item) => (
                  <option key={item.kind} value={item.kind}>{item.label}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" onClick={() => refresh().catch((err: Error) => setError(err.message))} aria-label="Refresh">
              <Icon name="refresh" />
            </button>
            <div className="layout-toggle" aria-label="View mode">
              <button className={layoutMode === 'details' ? 'selected' : ''} type="button" onClick={() => chooseLayoutMode('details')} aria-label="List view">
                <Icon name="view_list" />
              </button>
              <button className={layoutMode === 'cards' ? 'selected' : ''} type="button" onClick={() => chooseLayoutMode('cards')} aria-label="Grid view">
                <Icon name="grid_view" />
              </button>
            </div>
          </div>
        </header>

        <section className="content-panel">
          <div className="content-heading">
            <div>
              <p className="gallery-eyebrow">Workspace storage</p>
              <h1>{activeRole === 'all' ? 'All files' : roleLabels[activeRole]}</h1>
            </div>
            <div className="content-counts">
              <span>{visibleFolders.length} folders</span>
              <span>{filteredFiles.length} files</span>
            </div>
          </div>

          {error ? <div className="gallery-error">{error}</div> : null}

          {viewMode === 'custom' ? (
            <section className="custom-view-bar" aria-label="Custom Gallery view">
              <div>
                <Icon name="filter_list" />
                <strong>{customTitle || 'Custom file view'}</strong>
                <small>{filteredFiles.length} visible files from {customFileIds.length + customWorkspacePaths.length} selected references</small>
              </div>
              <button type="button" onClick={clearCustomFileView}>Clear custom view</button>
            </section>
          ) : null}

          {viewMode !== 'custom' ? (
            <section className="folder-bar" aria-label="Folder navigation">
              <nav className="folder-breadcrumbs" aria-label="Current folder">
                {breadcrumbItems(currentFolderPath).map((item, index, items) => (
                  <button
                    key={item.path || 'root'}
                    className={index === items.length - 1 ? 'selected' : ''}
                    type="button"
                    onClick={() => setCurrentFolderPath(item.path)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={() => moveDraggedFile(item.path).catch((err: Error) => setError(err.message))}
                  >
                    {index === 0 ? <Icon name="home_storage" /> : null}
                    <span>{item.label}</span>
                  </button>
                ))}
              </nav>
              <form
                className="new-folder-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  createCurrentFolder().catch((err: Error) => setError(err.message));
                }}
              >
                <input value={newFolderName} onChange={(event) => setNewFolderName(event.target.value)} placeholder="New folder" aria-label="New folder name" />
                <button type="submit">
                  <Icon name="create_new_folder" />
                  Create
                </button>
              </form>
              <div className="upload-control">
                <input
                  ref={uploadInputRef}
                  type="file"
                  multiple
                  onChange={(event) => {
                    const selected = Array.from(event.currentTarget.files || []);
                    event.currentTarget.value = '';
                    if (selected.length) uploadSelectedFiles(selected).catch((err: Error) => setError(err.message));
                  }}
                />
                <button
                  className="upload-button"
                  type="button"
                  onClick={requestUpload}
                  disabled={uploading}
                  aria-label="Upload file to current folder"
                  title={activeRole === 'all' ? 'Choose Generated or Uploaded before uploading' : `Upload to ${roleLabels[activeRole]}${currentFolderPath ? ` / ${currentFolderPath}` : ''}`}
                >
                  <Icon name="upload_file" />
                  {uploading ? 'Uploading' : 'Upload'}
                </button>
              </div>
            </section>
          ) : null}

          {selectedFile ? (
            <section className="selection-bar" aria-label="Selected file actions">
              <div>
                <Icon name={iconForKind(selectedFile.preview_kind)} />
                <strong>{selectedFile.name}</strong>
              </div>
              <button className="icon-button" type="button" onClick={() => download(selectedFile).catch((err: Error) => setError(err.message))} aria-label="Download selected file">
                <Icon name="download" />
              </button>
              <button className="icon-button danger" type="button" onClick={() => removeFile(selectedFile).catch((err: Error) => setError(err.message))} aria-label="Delete selected file">
                <Icon name="delete" />
              </button>
            </section>
          ) : null}

          {layoutMode === 'cards' ? (
            <section className="gallery-grid" aria-label="Workspace gallery">
              {visibleFolders.length ? <h2 className="content-section-title">Folders</h2> : null}
              {visibleFolders.map((folder) => (
                <FolderCard
                  key={folder.id}
                  folder={folder}
                  onOpen={() => openFolder(folder)}
                  onDropFile={(targetFolder) => moveDraggedFile(targetFolder.relative_path, targetFolder.role).catch((err: Error) => setError(err.message))}
                />
              ))}
              {filteredFiles.length ? <h2 className="content-section-title files-title">Files</h2> : null}
              {filteredFiles.map((file) => (
                <FileCard
                  key={file.id}
                  file={file}
                  selected={selectedFile?.id === file.id}
                  onOpen={() => setSelectedFile(file)}
                  onDownload={() => download(file).catch((err: Error) => setError(err.message))}
                  onDelete={() => removeFile(file).catch((err: Error) => setError(err.message))}
                  onDragStart={() => setDraggedFile(file)}
                  onDragEnd={() => setDraggedFile(null)}
                />
              ))}
              {!filteredFiles.length && !visibleFolders.length ? <div className="empty-state">{viewMode === 'custom' ? 'No files from this custom view are currently available.' : 'No folders or files here yet.'}</div> : null}
            </section>
          ) : (
            <section className="gallery-details" aria-label="Workspace gallery details" role="table">
              <div className="details-head" role="row">
                <span role="columnheader">Name</span>
                <span role="columnheader">Type</span>
                <span role="columnheader">Storage</span>
                <span role="columnheader">Size</span>
                <span role="columnheader">Modified</span>
                <span role="columnheader" aria-label="Actions" />
              </div>
              <div className="details-body" role="rowgroup">
                {visibleFolders.map((folder) => (
                  <DetailFolderRow
                    key={folder.id}
                    folder={folder}
                    onOpen={() => openFolder(folder)}
                    onDropFile={(targetFolder) => moveDraggedFile(targetFolder.relative_path, targetFolder.role).catch((err: Error) => setError(err.message))}
                  />
                ))}
                {filteredFiles.map((file) => (
                  <DetailFileRow
                    key={file.id}
                    file={file}
                    selected={selectedFile?.id === file.id}
                    onOpen={() => setSelectedFile(file)}
                    onDownload={() => download(file).catch((err: Error) => setError(err.message))}
                    onDelete={() => removeFile(file).catch((err: Error) => setError(err.message))}
                    onDragStart={() => setDraggedFile(file)}
                    onDragEnd={() => setDraggedFile(null)}
                  />
                ))}
                {!filteredFiles.length && !visibleFolders.length ? <div className="empty-state details-empty">{viewMode === 'custom' ? 'No files from this custom view are currently available.' : 'No folders or files here yet.'}</div> : null}
              </div>
            </section>
          )}
        </section>
      </section>

      <aside className="inspector-panel" aria-label="File details">
        {selectedFile ? (
          <>
            <header className="inspector-header">
              <div>
                <p className="gallery-eyebrow">{roleLabels[selectedFile.role]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2>{selectedFile.name}</h2>
              </div>
              <button className="icon-button" onClick={() => setSelectedFile(null)} aria-label="Close details">
                <Icon name="close" />
              </button>
            </header>
            <div className="inspector-preview">
              {markdownEditing && selectedFile.preview_kind === 'markdown' ? (
                <div className="markdown-editor">
                  <textarea
                    value={markdownDraft}
                    onChange={(event) => setMarkdownDraft(event.target.value)}
                    aria-label="Markdown source"
                    spellCheck
                  />
                  <section className="markdown-editor-preview" aria-label="Rendered Markdown preview">
                    <MarkdownPreview text={markdownDraft} />
                  </section>
                </div>
              ) : (
                <GalleryPreview file={selectedFile} previewUrl={previewUrl} previewText={previewText} previewTable={previewTable} />
              )}
            </div>
            <section className="inspector-actions" aria-label="File preview actions">
              <button className="primary-action" onClick={() => setPreviewModalOpen(true)} type="button">
                <Icon name="open_in_new" />
                Preview
              </button>
            </section>
            <section className="inspector-section">
              <h3>Details</h3>
              <dl>
                <div><dt>Path</dt><dd>{selectedFile.workspace_relative_path}</dd></div>
                <div><dt>Size</dt><dd>{formatBytes(selectedFile.size_bytes)}</dd></div>
                <div><dt>Modified</dt><dd>{new Date(selectedFile.modified_at).toLocaleString()}</dd></div>
                <div><dt>Type</dt><dd>{selectedFile.content_type}</dd></div>
              </dl>
            </section>
            <section className="inspector-section">
              <h3>Rename</h3>
              <div className="rename-group">
                <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label="File name" />
                <button onClick={() => saveRename().catch((err: Error) => setError(err.message))}>Rename</button>
              </div>
            </section>
            {selectedFile.preview_kind === 'markdown' ? (
              <section className="inspector-section markdown-actions">
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
          </>
        ) : (
          <div className="inspector-empty">
            <Icon name="info" />
            <h2>Details</h2>
            <p>Select a file to inspect metadata, rename it, or open the preview.</p>
          </div>
        )}
      </aside>
      {previewModalOpen && selectedFile ? (
        <div className="preview-modal-backdrop" onMouseDown={() => setPreviewModalOpen(false)}>
          <section className="preview-modal" role="dialog" aria-modal="true" aria-labelledby="preview-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="preview-modal-header">
              <div>
                <p className="gallery-eyebrow">{roleLabels[selectedFile.role]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2 id="preview-modal-title">{selectedFile.name}</h2>
              </div>
              <button className="icon-button" type="button" onClick={() => setPreviewModalOpen(false)} aria-label="Close preview">
                <Icon name="close" />
              </button>
            </header>
            <div className="preview-modal-body">
              <GalleryPreview file={selectedFile} previewUrl={previewUrl} previewText={previewText} previewTable={previewTable} />
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}

async function readFullFileText(file: GalleryFile) {
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
