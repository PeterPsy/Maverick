import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { loadCatalog, loadViewFilter, setViewFilter } from '../../galleryApi';
import { formatBytes, iconForKind, kindLabels, roleLabels } from '../../galleryMeta';
import { Icon } from '../../Icon';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { gallerySelectionFromMessage, type ActiveGallerySelectionMessage } from '../../lib/activeGallerySelection';
import { galleryTargetFromWidgetContext, type GalleryNavigationTarget } from '../../lib/galleryNavigationParams';
import type { GalleryFile, GalleryViewFilter } from '../../types';
import '../../styles/sidebar-widget.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

type ViewFilterPayload = {
  state?: {
    view_filter?: GalleryViewFilter;
  };
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

function openFileInShell(file: GalleryFile) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'gallery',
      params: {
        file_id: file.id,
        workspace_relative_path: file.workspace_relative_path
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function fileIdentity(file: GalleryFile) {
  return file.id || file.workspace_relative_path;
}

function targetIdentity(target: GalleryNavigationTarget | null) {
  return target?.fileId || target?.workspaceRelativePath || '';
}

function fileMatchesSearch(file: GalleryFile, query: string) {
  if (!query) return true;
  return `${file.name} ${file.workspace_relative_path} ${file.content_type} ${file.preview_kind} ${file.role}`.toLowerCase().includes(query);
}

function GallerySidebarWidget() {
  const [files, setFiles] = useState<GalleryFile[]>([]);
  const [query, setQuery] = useState('');
  const [selectedFileIdentity, setSelectedFileIdentity] = useState('');
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files.filter((file) => fileMatchesSearch(file, needle));
  }, [files, query]);

  async function refreshFiles() {
    const payload = await loadCatalog();
    setFiles(payload.files);
    setSelectedFileIdentity((current) => {
      if (current && payload.files.some((file) => file.id === current || file.workspace_relative_path === current)) {
        return current;
      }
      return payload.files[0] ? fileIdentity(payload.files[0]) : '';
    });
  }

  async function refreshViewFilter() {
    const payload = (await loadViewFilter()) as ViewFilterPayload;
    const nextQuery = payload.state?.view_filter?.query || '';
    lastPersistedQueryRef.current = nextQuery;
    hasLoadedViewStateRef.current = true;
    setQuery(nextQuery);
  }

  async function refreshAll() {
    try {
      await Promise.all([refreshFiles(), refreshViewFilter()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Gallery.');
    } finally {
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (!hasLoadedViewStateRef.current || query === lastPersistedQueryRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = query.trim();
      setViewFilter({ query: nextQuery })
        .then(() => {
          lastPersistedQueryRef.current = nextQuery;
          setError(null);
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

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
      } & ActiveGallerySelectionMessage;
      const contextTarget = galleryTargetFromWidgetContext(payload);
      if (contextTarget) {
        setSelectedFileIdentity(targetIdentity(contextTarget));
        return;
      }
      const activeTarget = gallerySelectionFromMessage(payload);
      if (activeTarget) {
        setSelectedFileIdentity(targetIdentity(activeTarget));
        return;
      }
      if (payload.type !== 'maverick.widget.data-changed' || payload.owner_app_id !== 'gallery') {
        return;
      }
      if (payload.resource === 'files') {
        void refreshFiles();
      }
      if (payload.resource === 'view-state') {
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function selectFile(file: GalleryFile) {
    setSelectedFileIdentity(fileIdentity(file));
    openFileInShell(file);
  }

  return (
    <main className={`gallery-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="gallery-sidebar-search-frame">
        <Icon name="search" />
        <input
          aria-label="Search Gallery"
          className="gallery-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search files"
          value={query}
        />
      </div>

      {error ? <p className="gallery-sidebar-empty">{error}</p> : null}

      <div className="gallery-sidebar-list">
        {isInitialLoading ? (
          <GallerySidebarSkeleton />
        ) : filteredFiles.length ? (
          filteredFiles.map((file) => (
            <button
              className={`gallery-sidebar-row ${file.id === selectedFileIdentity || file.workspace_relative_path === selectedFileIdentity ? 'is-active' : ''}`}
              key={file.id}
              onClick={() => selectFile(file)}
              type="button"
            >
              <span className="gallery-sidebar-row__icon" aria-hidden="true">
                <Icon name={iconForKind(file.preview_kind)} />
              </span>
              <span className="gallery-sidebar-row__copy">
                <strong>{file.name}</strong>
                <span>{kindLabels[file.preview_kind]} · {roleLabels[file.role]} · {formatBytes(file.size_bytes)}</span>
              </span>
            </button>
          ))
        ) : (
          <p className="gallery-sidebar-empty">No files found.</p>
        )}
      </div>
    </main>
  );
}

function GallerySidebarSkeleton() {
  return (
    <div aria-hidden="true" className="gallery-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="gallery-sidebar-skeleton__row" key={index}>
          <span className="gallery-sidebar-skeleton__icon" />
          <span className="gallery-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('gallery-sidebar-root') as HTMLElement).render(<GallerySidebarWidget />);
