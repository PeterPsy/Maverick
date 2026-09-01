import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { callBackend, listDynamicViews } from '../../api';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { dynamicViewIdFromSelectionMessage, type ActiveDynamicViewSelectionMessage } from '../../lib/activeDynamicViewSelection';
import { dynamicViewIdFromWidgetContext } from '../../lib/dynamicViewNavigationParams';
import {
  DEFAULT_VIEW_FILTER,
  listOptionsFromFilter,
  selectedViewIdsFromFilter,
  viewMatchesSearch,
  type ViewFilter
} from '../../lib/dynamicViewSidebarFilters';
import type { DynamicViewInstance } from '../../types';
import '../../styles/sidebar-widget.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

type ViewFilterPayload = {
  state?: {
    view_filter?: ViewFilter;
  };
};

type RefreshViewFilterOptions = {
  syncQuery?: boolean;
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
    "*"
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, "*");
  }
}

function DynamicViewsSidebarWidget() {
  const [items, setItems] = useState<DynamicViewInstance[]>([]);
  const [query, setQuery] = useState('');
  const [selectedViewId, setSelectedViewId] = useState('');
  const [viewFilter, setViewFilter] = useState<ViewFilter>(DEFAULT_VIEW_FILTER);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);
  const queryRef = useRef('');
  const saveRequestSeqRef = useRef(0);
  const viewFilterRef = useRef<ViewFilter>(DEFAULT_VIEW_FILTER);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => viewMatchesSearch(item, needle));
  }, [items, query]);

  async function refreshViews(filter: ViewFilter = viewFilterRef.current) {
    if (filter.mode === 'custom' && !selectedViewIdsFromFilter(filter).length) {
      setItems([]);
      setSelectedViewId('');
      return;
    }
    const payload = await listDynamicViews(listOptionsFromFilter(filter));
    setItems(payload.items);
    setSelectedViewId((current) => {
      if (current && payload.items.some((item) => item.id === current)) {
        return current;
      }
      return payload.items[0]?.id || '';
    });
  }

  function rememberViewFilter(nextFilter: ViewFilter) {
    viewFilterRef.current = nextFilter;
    setViewFilter(nextFilter);
  }

  async function refreshViewFilter(options: RefreshViewFilterOptions = {}) {
    const payload = await callBackend<ViewFilterPayload>({ action: 'view_filter' });
    const nextFilter = payload.state?.view_filter || DEFAULT_VIEW_FILTER;
    const nextQuery = nextFilter.query || '';
    lastPersistedQueryRef.current = nextQuery;
    hasLoadedViewStateRef.current = true;
    rememberViewFilter(nextFilter);
    if (options.syncQuery !== false) {
      setQuery(nextQuery);
    }
    return nextFilter;
  }

  async function refreshAll() {
    try {
      const nextFilter = await refreshViewFilter();
      await refreshViews(nextFilter);
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
    viewFilterRef.current = viewFilter;
  }, [viewFilter]);

  useEffect(() => {
    queryRef.current = query;
  }, [query]);

  useEffect(() => {
    const nextQuery = query.trim();
    if (!hasLoadedViewStateRef.current || nextQuery === lastPersistedQueryRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const requestSeq = saveRequestSeqRef.current + 1;
      saveRequestSeqRef.current = requestSeq;
      callBackend<ViewFilterPayload>({
        action: 'set_view_filter',
        preserve_custom: false,
        query: nextQuery,
        status: viewFilter.status || 'all'
      })
        .then((payload) => {
          if (requestSeq !== saveRequestSeqRef.current || nextQuery !== queryRef.current.trim()) {
            return;
          }
          const nextFilter = payload.state?.view_filter || { ...viewFilter, query: nextQuery };
          rememberViewFilter(nextFilter);
          lastPersistedQueryRef.current = nextQuery;
          setError(null);
          void refreshViews(nextFilter).catch((loadError: Error) => setError(loadError.message));
        })
        .catch((saveError: Error) => {
          if (requestSeq === saveRequestSeqRef.current && nextQuery === queryRef.current.trim()) {
            setError(saveError.message);
          }
        });
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query, viewFilter.status]);

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
        const hasLocalQueryChange = queryRef.current.trim() !== lastPersistedQueryRef.current;
        void refreshViewFilter({ syncQuery: !hasLocalQueryChange })
          .then((nextFilter) => {
            if (!hasLocalQueryChange) {
              return refreshViews(nextFilter);
            }
            return undefined;
          })
          .catch((loadError: Error) => setError(loadError.message));
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
          <p className="dynamic-views-sidebar-empty">
            {viewFilter.mode === 'custom' && !query.trim() ? 'No selected dynamic views available.' : 'No dynamic views found.'}
          </p>
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
