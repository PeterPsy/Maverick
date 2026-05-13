import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { callBackend, listDynamicViews } from '../../api';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { dynamicViewIdFromSelectionMessage, type ActiveDynamicViewSelectionMessage } from '../../lib/activeDynamicViewSelection';
import { dynamicViewIdFromWidgetContext } from '../../lib/dynamicViewNavigationParams';
import type { DynamicViewInstance } from '../../types';
import '../../styles/sidebar-widget.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

type ViewFilter = {
  mode?: string;
  query?: string;
  status?: string;
};

type ViewFilterPayload = {
  state?: {
    view_filter?: ViewFilter;
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

function openDynamicViewInShell(viewId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'dynamic-views',
      params: {
        app_page: `views/${encodeURIComponent(viewId)}`,
        instance_id: viewId,
        view_id: viewId
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function viewMatchesSearch(view: DynamicViewInstance, query: string) {
  if (!query) return true;
  return `${view.title} ${view.summary} ${view.id} ${view.snapshot_mode}`.toLowerCase().includes(query);
}

function DynamicViewsSidebarWidget() {
  const [items, setItems] = useState<DynamicViewInstance[]>([]);
  const [query, setQuery] = useState('');
  const [selectedViewId, setSelectedViewId] = useState('');
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => viewMatchesSearch(item, needle));
  }, [items, query]);

  async function refreshViews() {
    const payload = await listDynamicViews();
    setItems(payload.items);
    setSelectedViewId((current) => {
      if (current && payload.items.some((item) => item.id === current)) {
        return current;
      }
      return payload.items[0]?.id || '';
    });
  }

  async function refreshViewFilter() {
    const payload = await callBackend<ViewFilterPayload>({ action: 'view_filter' });
    const nextQuery = payload.state?.view_filter?.query || '';
    lastPersistedQueryRef.current = nextQuery;
    hasLoadedViewStateRef.current = true;
    setQuery(nextQuery);
  }

  async function refreshAll() {
    try {
      await Promise.all([refreshViews(), refreshViewFilter()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load dynamic views.');
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
      callBackend<ViewFilterPayload>({ action: 'set_view_filter', query: nextQuery, status: 'all' })
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
        context?: {
          content?: {
            payload?: unknown;
          };
        };
        owner_app_id?: string;
        resource?: string;
        type?: string;
      } & ActiveDynamicViewSelectionMessage;
      const contextViewId = dynamicViewIdFromWidgetContext(payload);
      if (contextViewId) {
        setSelectedViewId(contextViewId);
        return;
      }
      const activeViewId = dynamicViewIdFromSelectionMessage(payload);
      if (activeViewId) {
        setSelectedViewId(activeViewId);
        return;
      }
      if (payload.type !== 'maverick.widget.data-changed' || payload.owner_app_id !== 'dynamic-views') {
        return;
      }
      if (payload.resource === 'views') {
        void refreshViews();
      }
      if (payload.resource === 'view-state') {
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function selectView(view: DynamicViewInstance) {
    setSelectedViewId(view.id);
    openDynamicViewInShell(view.id);
  }

  return (
    <main className={`dynamic-views-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="dynamic-views-sidebar-search-frame">
        <span className="material-symbols-rounded" aria-hidden="true">search</span>
        <input
          aria-label="Search dynamic views"
          className="dynamic-views-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search views"
          value={query}
        />
      </div>

      {error ? <p className="dynamic-views-sidebar-empty">{error}</p> : null}

      <div className="dynamic-views-sidebar-list">
        {isInitialLoading ? (
          <DynamicViewsSidebarSkeleton />
        ) : filteredItems.length ? (
          filteredItems.map((view) => (
            <button
              className={`dynamic-views-sidebar-row ${view.id === selectedViewId ? 'is-active' : ''}`}
              key={view.id}
              onClick={() => selectView(view)}
              type="button"
            >
              <span className="material-symbols-rounded dynamic-views-sidebar-row__icon" aria-hidden="true">dashboard_customize</span>
              <span className="dynamic-views-sidebar-row__copy">
                <strong>{view.title}</strong>
                <span>{view.summary || view.snapshot_mode}</span>
              </span>
            </button>
          ))
        ) : (
          <p className="dynamic-views-sidebar-empty">No dynamic views found.</p>
        )}
      </div>
    </main>
  );
}

function DynamicViewsSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="dynamic-views-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="dynamic-views-sidebar-skeleton__row" key={index}>
          <span className="dynamic-views-sidebar-skeleton__icon" />
          <span className="dynamic-views-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('dynamic-views-sidebar-root') as HTMLElement).render(<DynamicViewsSidebarWidget />);
