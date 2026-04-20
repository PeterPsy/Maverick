import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { decodeBase64, loadCatalog, readFile, renameFile } from './galleryApi';
import { formatBytes, iconForKind, kindLabels, roleLabels } from './galleryMeta';
import type { FileRole, GalleryFile } from './types';
import './styles/main.css';

const PREVIEW_BYTES = 8 * 1024 * 1024;
const DOWNLOAD_BYTES = 100 * 1024 * 1024;

function canInlinePreview(file: GalleryFile) {
  return ['image', 'video', 'audio', 'text', 'markdown', 'pdf'].includes(file.preview_kind);
}

function GalleryPreview({ file, previewUrl, previewText }: { file: GalleryFile; previewUrl: string; previewText: string }) {
  if (file.preview_kind === 'image' && previewUrl) return <img src={previewUrl} alt={file.name} />;
  if (file.preview_kind === 'video' && previewUrl) return <video src={previewUrl} controls />;
  if (file.preview_kind === 'audio' && previewUrl) return <audio src={previewUrl} controls />;
  if (file.preview_kind === 'pdf' && previewUrl) return <iframe src={previewUrl} title={file.name} />;
  if (['text', 'markdown'].includes(file.preview_kind)) return <pre>{previewText || 'Loading preview...'}</pre>;
  return (
    <div className="format-preview">
      <span className="material-symbols-rounded" aria-hidden="true">{iconForKind(file.preview_kind)}</span>
      <strong>{kindLabels[file.preview_kind]}</strong>
      <p>{file.name}</p>
      <small>Preview metadata is available. Download this file to open it with the native editor or viewer.</small>
    </div>
  );
}

function FileCard({ file, selected, onOpen, onDownload }: {
  file: GalleryFile;
  selected: boolean;
  onOpen: () => void;
  onDownload: () => void;
}) {
  return (
    <button className={selected ? 'gallery-card selected' : 'gallery-card'} onClick={onOpen} type="button">
      <span className="gallery-card-icon material-symbols-rounded" aria-hidden="true">{iconForKind(file.preview_kind)}</span>
      <span className="gallery-card-role">{roleLabels[file.role]}</span>
      <span className="gallery-card-main">
        <strong>{file.name}</strong>
        <span>{kindLabels[file.preview_kind]} · {formatBytes(file.size_bytes)}</span>
      </span>
      <span className="gallery-card-path">{file.workspace_relative_path}</span>
      <span
        className="card-download material-symbols-rounded"
        aria-label={`Download ${file.name}`}
        role="button"
        tabIndex={0}
        onClick={(event) => {
          event.stopPropagation();
          onDownload();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            event.stopPropagation();
            onDownload();
          }
        }}
      >
        download
      </span>
    </button>
  );
}

function App() {
  const [files, setFiles] = useState<GalleryFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<GalleryFile | null>(null);
  const [activeRole, setActiveRole] = useState<FileRole | 'all'>('all');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [error, setError] = useState('');

  async function refresh() {
    const payload = await loadCatalog();
    setFiles(payload.files);
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, []);

  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files.filter((file) => {
      const roleMatch = activeRole === 'all' || file.role === activeRole;
      const kindMatch = kind === 'all' || file.preview_kind === kind;
      const textMatch = !needle || `${file.name} ${file.workspace_relative_path} ${file.content_type}`.toLowerCase().includes(needle);
      return roleMatch && kindMatch && textMatch;
    });
  }, [activeRole, files, kind, query]);

  const stats = useMemo(() => ({
    all: files.length,
    generated: files.filter((file) => file.role === 'generated').length,
    uploaded: files.filter((file) => file.role === 'uploaded').length
  }), [files]);

  useEffect(() => {
    setPreviewText('');
    setPreviewUrl('');
    setRenameValue(selectedFile?.name || '');
    if (!selectedFile || !canInlinePreview(selectedFile)) return;
    let active = true;
    let objectUrl = '';
    readFile(selectedFile, PREVIEW_BYTES)
      .then((payload) => {
        if (!active) return;
        const blob = decodeBase64(payload.content_base64, payload.file.content_type);
        if (['text', 'markdown'].includes(payload.file.preview_kind)) {
          blob.text().then((text) => active && setPreviewText(text));
        } else {
          objectUrl = URL.createObjectURL(blob);
          setPreviewUrl(objectUrl);
        }
      })
      .catch((err: Error) => active && setError(err.message));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
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
            <button key={role} className={activeRole === role ? 'selected' : ''} onClick={() => setActiveRole(role)}>
              <span>{role === 'all' ? 'All' : roleLabels[role]}</span>
              <strong>{stats[role]}</strong>
            </button>
          ))}
        </div>
        <input className="gallery-search" placeholder="Search files" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select className="gallery-select" value={kind} onChange={(event) => setKind(event.target.value)}>
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

      <section className="gallery-grid" aria-label="Workspace gallery">
        {filteredFiles.map((file) => (
          <FileCard
            key={file.id}
            file={file}
            selected={selectedFile?.id === file.id}
            onOpen={() => setSelectedFile(file)}
            onDownload={() => download(file).catch((err: Error) => setError(err.message))}
          />
        ))}
        {!filteredFiles.length ? <div className="empty-state">No files in workspace storage yet.</div> : null}
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
            </footer>
          </section>
        </div>
      ) : null}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
