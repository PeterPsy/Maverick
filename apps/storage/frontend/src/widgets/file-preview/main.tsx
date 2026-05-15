import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { callBackend, decodeBase64, readFile } from '../../storageApi';
import { iconForKind, kindLabels } from '../../storageMeta';
import { Icon } from '../../Icon';
import { MarkdownPreview } from '../../markdownPreview';
import type { StorageFile } from '../../types';
import './styles.css';

type WidgetContext = {
  content?: {
    payload?: Record<string, unknown>;
  };
};

const PREVIEW_BYTES = 8 * 1024 * 1024;
const WIDGET_MIN_HEIGHT_PX = 320;
const WIDGET_MAX_HEIGHT_PX = 520;

function contextToken() {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get('context') || new URLSearchParams(window.location.search).get('context') || '';
}

async function loadWidgetContext(): Promise<WidgetContext> {
  const token = contextToken();
  if (!token) throw new Error('Missing widget context.');
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) throw new Error('Unable to load widget context.');
  return (await response.json()).context as WidgetContext;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function fileReference(payload: Record<string, unknown>) {
  const nested = typeof payload.file === 'object' && payload.file !== null ? payload.file as Record<string, unknown> : {};
  return {
    role: firstString(payload.role, nested.role),
    relative_path: firstString(payload.relative_path, nested.relative_path),
    workspace_relative_path: firstString(payload.workspace_relative_path, nested.workspace_relative_path, payload.path, nested.path)
  };
}

function canInlinePreview(file: StorageFile) {
  return ['image', 'video', 'audio', 'text', 'markdown', 'pdf'].includes(file.preview_kind);
}

function openStorage(file?: StorageFile) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'storage',
      params: file ? { workspace_relative_path: file.workspace_relative_path } : {}
    },
    window.location.origin
  );
}

function postWidgetResize(element: HTMLElement, scrollElement?: HTMLElement | null) {
  const visibleHeight = Math.ceil(element.getBoundingClientRect().height);
  const scrollHeight = scrollElement
    ? Math.max(
        scrollElement.scrollHeight,
        scrollElement.firstElementChild instanceof HTMLElement ? scrollElement.firstElementChild.scrollHeight : 0
      )
    : 0;
  const chromeHeight = scrollElement ? Math.max(0, element.scrollHeight - scrollElement.clientHeight) : 0;
  const contentHeight = Math.max(element.scrollHeight, visibleHeight, scrollHeight + chromeHeight);
  const height = Math.min(WIDGET_MAX_HEIGHT_PX, Math.max(WIDGET_MIN_HEIGHT_PX, contentHeight));
  window.parent?.postMessage(
    {
      type: 'maverick.widget.resize',
      owner_app_id: 'storage',
      widget_id: 'file-preview',
      height: `${height}px`,
      width: '100%'
    },
    window.location.origin
  );
}

function Preview({ file, loading, previewUrl, previewText }: { file: StorageFile; loading: boolean; previewUrl: string; previewText: string }) {
  if (file.preview_kind === 'image' && previewUrl) return <img src={previewUrl} alt={file.name} />;
  if (file.preview_kind === 'video' && previewUrl) return <video src={previewUrl} controls />;
  if (file.preview_kind === 'audio' && previewUrl) return <audio src={previewUrl} controls />;
  if (file.preview_kind === 'pdf' && previewUrl) return <iframe src={previewUrl} title={file.name} />;
  if (file.preview_kind === 'markdown') return previewText ? <MarkdownPreview text={previewText} compact /> : <pre>Loading preview...</pre>;
  if (file.preview_kind === 'text') return <pre>{previewText || 'Loading preview...'}</pre>;
  const isLoadingMediaPreview = loading && (file.preview_kind === 'image' || file.preview_kind === 'video');
  return (
    <div className={`file-widget__fallback ${isLoadingMediaPreview ? 'is-loading-preview' : ''}`}>
      <Icon name={iconForKind(file.preview_kind)} />
      <strong>{kindLabels[file.preview_kind]}</strong>
      <p>Open in Storage or download from the app to inspect this file.</p>
    </div>
  );
}

function StorageFilePreviewWidget() {
  const rootRef = useRef<HTMLElement | null>(null);
  const documentRef = useRef<HTMLElement | null>(null);
  const scrollIdleTimerRef = useRef<number | null>(null);
  const [file, setFile] = useState<StorageFile | null>(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [isScrolling, setIsScrolling] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    loadWidgetContext()
      .then((context) => {
        const payload = context.content?.payload || {};
        return callBackend<{ file: StorageFile }>({ action: 'file_info', ...fileReference(payload) });
      })
      .then((result) => setFile(result.file))
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    setPreviewText('');
    setPreviewUrl('');
    setPreviewLoading(Boolean(file && canInlinePreview(file)));
    if (!file || !canInlinePreview(file)) return;
    let active = true;
    let objectUrl = '';
    readFile(file, PREVIEW_BYTES)
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
      .catch((previewError: Error) => active && setError(previewError.message))
      .finally(() => {
        if (active) setPreviewLoading(false);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file]);

  useEffect(() => {
    const element = rootRef.current;
    if (!element) return undefined;
    const update = () => postWidgetResize(element, documentRef.current);
    update();
    const frame = window.requestAnimationFrame(update);
    const delayedUpdate = window.setTimeout(update, 120);
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null;
    observer?.observe(element);
    if (documentRef.current) observer?.observe(documentRef.current);
    element.addEventListener('load', update, true);
    element.addEventListener('loadedmetadata', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(delayedUpdate);
      observer?.disconnect();
      element.removeEventListener('load', update, true);
      element.removeEventListener('loadedmetadata', update, true);
      window.removeEventListener('resize', update);
    };
  }, [error, file, previewLoading, previewText, previewUrl]);

  useEffect(() => {
    return () => {
      if (scrollIdleTimerRef.current !== null) window.clearTimeout(scrollIdleTimerRef.current);
    };
  }, []);

  const handleDocumentScroll = () => {
    setIsScrolling(true);
    if (scrollIdleTimerRef.current !== null) window.clearTimeout(scrollIdleTimerRef.current);
    scrollIdleTimerRef.current = window.setTimeout(() => {
      setIsScrolling(false);
      scrollIdleTimerRef.current = null;
    }, 900);
  };

  if (error) {
    return <main className="file-widget file-widget--state" ref={rootRef}><p className="file-widget__empty">{error}</p></main>;
  }
  if (!file) {
    return (
      <main className="file-widget file-widget--skeleton" ref={rootRef} aria-busy="true" aria-label="Loading file preview">
        <header className="file-widget__bar">
          <span className="file-widget__skeleton-title" />
          <span className="file-widget__skeleton-icon" />
        </header>
        <section className="file-widget__skeleton-body" aria-hidden="true">
          <span className="file-widget__skeleton-line is-wide" />
          <span className="file-widget__skeleton-line" />
          <span className="file-widget__skeleton-line is-short" />
          <span className="file-widget__skeleton-block" />
        </section>
      </main>
    );
  }

  return (
    <main className="file-widget" ref={rootRef}>
      <header className="file-widget__bar">
        <h3>
          <button className="file-widget__title-button" type="button" onClick={() => openStorage(file)}>
            {file.name}
          </button>
        </h3>
        <button
          className="file-widget__open"
          type="button"
          onClick={() => openStorage(file)}
          aria-label={`Open ${file.name} in Storage`}
        >
          <Icon name="open_in_new" />
        </button>
      </header>
      <section
        className={`file-widget__document ${isScrolling ? 'is-scrolling' : ''}`}
        ref={documentRef}
        onScroll={handleDocumentScroll}
      >
        <Preview file={file} loading={previewLoading} previewUrl={previewUrl} previewText={previewText} />
      </section>
    </main>
  );
}

createRoot(document.getElementById('storage-file-preview-root') as HTMLElement).render(<StorageFilePreviewWidget />);
