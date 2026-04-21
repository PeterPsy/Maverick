import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { clearCustomView, decodeBase64, deleteFile, loadCatalog, loadViewFilter, readFile, renameFile, setViewFilter } from './galleryApi';
import { canInlinePreview, canTextPreview, FileCardPreview, GalleryPreview } from './filePreview';
import { formatBytes, kindLabels, roleLabels } from './galleryMeta';
import { loadFullPreview } from './previewCache';
import type { FileRole, GalleryFile, GalleryViewFilter, PreviewKind } from './types';
import './styles/main.css';

const DOWNLOAD_BYTES = 100 * 1024 * 1024;
const VIEW_SYNC_MS = 2000;

const viewKinds = new Set<PreviewKind | 'all'>(['all', 'image', 'video', 'audio', 'pdf', 'document', 'presentation', 'spreadsheet', 'markdown', 'text', 'file']);

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

function FileCard({ file, selected, onOpen, onDownload, onDelete }: {
  file: GalleryFile;
  selected: boolean;
  onOpen: () => void;
  onDownload: () => void;
  onDelete: () => void;
}) {
  return (
    <article className={selected ? 'gallery-card selected' : 'gallery-card'}>
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
        <button className="card-action material-symbols-rounded" aria-label={`Download ${file.name}`} onClick={onDownload} type="button">
          download
        </button>
        <button className="card-action danger material-symbols-rounded" aria-label={`Delete ${file.name}`} onClick={onDelete} type="button">
          delete
        </button>
      </span>
    </article>
  );
}

function App() {
  const [files, setFiles] = useState<GalleryFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<GalleryFile | null>(null);
  const [activeRole, setActiveRole] = useState<FileRole | 'all'>('all');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [viewMode, setViewMode] = useState<'search' | 'custom'>('search');
  const [customTitle, setCustomTitle] = useState('');
  const [customFileIds, setCustomFileIds] = useState<string[]>([]);
  const [customWorkspacePaths, setCustomWorkspacePaths] = useState<string[]>([]);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [error, setError] = useState('');
  const viewFilterUpdatedAtRef = useRef('');
  const viewFilterWriteRef = useRef<number | null>(null);
  const viewFilterPendingRef = useRef(false);

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
    setFiles(payload.files);
    applyRemoteViewFilter(normalizedViewFilter(payload.state.view_filter));
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
    };
  }, []);

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

  function clearCustomFileView() {
    clearCustomView()
      .then((payload) => applyRemoteViewFilter(normalizedViewFilter(payload.state.view_filter)))
      .catch((err: Error) => setError(err.message));
  }

  const customScopedFiles = useMemo(() => {
    const customIds = new Set(customFileIds);
    const customPaths = new Set(customWorkspacePaths);
    if (viewMode !== 'custom') return files;
    return files.filter((file) => customIds.has(file.id) || customPaths.has(file.workspace_relative_path));
  }, [customFileIds, customWorkspacePaths, files, viewMode]);

  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return customScopedFiles.filter((file) => {
      const roleMatch = activeRole === 'all' || file.role === activeRole;
      const kindMatch = kind === 'all' || file.preview_kind === kind;
      const textMatch = !needle || `${file.name} ${file.workspace_relative_path} ${file.content_type}`.toLowerCase().includes(needle);
      return roleMatch && kindMatch && textMatch;
    });
  }, [activeRole, customScopedFiles, kind, query]);

  const stats = useMemo(() => ({
    all: customScopedFiles.length,
    generated: customScopedFiles.filter((file) => file.role === 'generated').length,
    uploaded: customScopedFiles.filter((file) => file.role === 'uploaded').length
  }), [customScopedFiles]);

  useEffect(() => {
    setPreviewText('');
    setPreviewUrl('');
    setRenameValue(selectedFile?.name || '');
    if (!selectedFile || (!canInlinePreview(selectedFile) && !canTextPreview(selectedFile))) return;
    let active = true;
    loadFullPreview(selectedFile)
      .then((payload) => {
        if (!active) return;
        setPreviewText(payload.text);
        setPreviewUrl(payload.url);
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

  async function removeFile(file: GalleryFile) {
    if (!window.confirm(`Delete ${file.name}? This removes the file from workspace storage.`)) return;
    await deleteFile(file);
    setFiles((current) => current.filter((item) => item.id !== file.id));
    if (selectedFile?.id === file.id) setSelectedFile(null);
  }

  return (
    <main className="gallery-shell">
      <header className="gallery-topbar">
        <div>
          <p className="gallery-eyebrow">Workspace Storage</p>
          <h1>Gallery</h1>
        </div>
        <button className="icon-button" onClick={() => refresh().catch((err: Error) => setError(err.message))} aria-label="Refresh">
          <span className="material-symbols-rounded" aria-hidden="true">refresh</span>
        </button>
      </header>

      <section className="gallery-toolbar">
        <div className="role-tabs" aria-label="File sections">
          {(['all', 'generated', 'uploaded'] as const).map((role) => (
            <button key={role} className={activeRole === role ? 'selected' : ''} onClick={() => updateViewFilter({ role })}>
              <span>{role === 'all' ? 'All' : roleLabels[role]}</span>
              <strong>{stats[role]}</strong>
            </button>
          ))}
        </div>
        <input className="gallery-search" placeholder="Search files" value={query} onChange={(event) => updateViewFilter({ query: event.target.value })} />
        <select className="gallery-select" value={kind} onChange={(event) => updateViewFilter({ kind: event.target.value as PreviewKind | 'all' })}>
          <option value="all">All types</option>
          <option value="image">Images</option>
          <option value="video">Video</option>
          <option value="audio">Audio</option>
          <option value="pdf">PDF</option>
          <option value="document">Docs</option>
          <option value="presentation">Decks</option>
          <option value="spreadsheet">Sheets</option>
          <option value="markdown">Markdown</option>
          <option value="text">Text</option>
          <option value="file">Other files</option>
        </select>
      </section>

      {error ? <div className="gallery-error">{error}</div> : null}

      {viewMode === 'custom' ? (
        <section className="custom-view-bar" aria-label="Custom Gallery view">
          <div>
            <span className="material-symbols-rounded" aria-hidden="true">filter_list</span>
            <strong>{customTitle || 'Custom file view'}</strong>
            <small>{filteredFiles.length} visible files from {customFileIds.length + customWorkspacePaths.length} selected references</small>
          </div>
          <button type="button" onClick={clearCustomFileView}>Clear custom view</button>
        </section>
      ) : null}

      <section className="gallery-grid" aria-label="Workspace gallery">
        {filteredFiles.map((file) => (
          <FileCard
            key={file.id}
            file={file}
            selected={selectedFile?.id === file.id}
            onOpen={() => setSelectedFile(file)}
            onDownload={() => download(file).catch((err: Error) => setError(err.message))}
            onDelete={() => removeFile(file).catch((err: Error) => setError(err.message))}
          />
        ))}
        {!filteredFiles.length ? <div className="empty-state">{viewMode === 'custom' ? 'No files from this custom view are currently available.' : 'No files in workspace storage yet.'}</div> : null}
      </section>

      {selectedFile ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`${selectedFile.name} preview`}>
          <section className="preview-modal">
            <header className="modal-header">
              <div>
                <p className="gallery-eyebrow">{roleLabels[selectedFile.role]} · {kindLabels[selectedFile.preview_kind]}</p>
                <h2>{selectedFile.name}</h2>
                <p>{selectedFile.workspace_relative_path}</p>
              </div>
              <button className="icon-button" onClick={() => setSelectedFile(null)} aria-label="Close preview">
                <span className="material-symbols-rounded" aria-hidden="true">close</span>
              </button>
            </header>
            <div className="modal-body">
              <GalleryPreview file={selectedFile} previewUrl={previewUrl} previewText={previewText} />
            </div>
            <footer className="modal-actions">
              <div className="rename-group">
                <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label="File name" />
                <button onClick={() => saveRename().catch((err: Error) => setError(err.message))}>Rename</button>
              </div>
              <div className="file-facts">
                <span>{formatBytes(selectedFile.size_bytes)}</span>
                <span>{new Date(selectedFile.modified_at).toLocaleString()}</span>
              </div>
              <button className="primary-action" onClick={() => download(selectedFile).catch((err: Error) => setError(err.message))}>
                <span className="material-symbols-rounded" aria-hidden="true">download</span>
                Download
              </button>
              <button className="danger-action" onClick={() => removeFile(selectedFile).catch((err: Error) => setError(err.message))}>
                <span className="material-symbols-rounded" aria-hidden="true">delete</span>
                Delete
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
