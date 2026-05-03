import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { callBackend } from '../../api';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { agentTypeIdFromWidgetContext } from '../../lib/agentNavigationParams';
import { agentTypeIdFromSelectionMessage, type ActiveAgentSelectionMessage } from '../../lib/activeAgentSelection';
import type { AgentType, Catalog } from '../../types';
import '../../styles/sidebar-widget.css';

const emptyCatalog: Catalog = { common_prompt: '', roles: [], agent_types: [] };
const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

type ViewFilter = {
  mode?: string;
  query?: string;
  entity_type?: string;
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

function openAgentInShell(agentTypeId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'agents',
      params: {
        app_page: `agent-types/${agentTypeId}`,
        agent_type_id: agentTypeId
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function AgentsSidebarWidget() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [query, setQuery] = useState('');
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState('');
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredAgentTypes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return catalog.agent_types;
    }
    return catalog.agent_types.filter((item) => `${item.name} ${item.description} ${item.role_id}`.toLowerCase().includes(needle));
  }, [catalog.agent_types, query]);

  async function refreshCatalog() {
    const next = await callBackend<Catalog>({ action: 'catalog' });
    setCatalog(next);
    setSelectedAgentTypeId((current) => {
      if (current && next.agent_types.some((item) => item.id === current)) {
        return current;
      }
      return next.agent_types[0]?.id || '';
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
      await Promise.all([refreshCatalog(), refreshViewFilter()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load agents.');
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
      callBackend<ViewFilterPayload>({ action: 'set_view_filter', query: nextQuery, entity_type: 'all' })
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
      } & ActiveAgentSelectionMessage;
      const contextAgentTypeId = agentTypeIdFromWidgetContext(payload);
      if (contextAgentTypeId) {
        setSelectedAgentTypeId(contextAgentTypeId);
        return;
      }
      const activeAgentTypeId = agentTypeIdFromSelectionMessage(payload);
      if (activeAgentTypeId) {
        setSelectedAgentTypeId(activeAgentTypeId);
        return;
      }
      if (payload.type !== 'maverick.widget.data-changed' || payload.owner_app_id !== 'agents') {
        return;
      }
      if (payload.resource === 'configuration') {
        void refreshCatalog();
      }
      if (payload.resource === 'view-state') {
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function selectAgent(agentType: AgentType) {
    setSelectedAgentTypeId(agentType.id);
    openAgentInShell(agentType.id);
  }

  return (
    <main className={`agents-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="agents-sidebar-search-frame">
        <span className="material-symbols-rounded" aria-hidden="true">search</span>
        <input
          aria-label="Search agents"
          className="agents-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search agents"
          value={query}
        />
      </div>

      {error ? <p className="agents-sidebar-empty">{error}</p> : null}

      <div className="agents-sidebar-list">
        {isInitialLoading ? (
          <AgentsSidebarSkeleton />
        ) : filteredAgentTypes.length ? (
          filteredAgentTypes.map((agentType) => (
            <button
              className={`agents-sidebar-row ${agentType.id === selectedAgentTypeId ? 'is-active' : ''}`}
              key={agentType.id}
              onClick={() => selectAgent(agentType)}
              type="button"
            >
              <span className="material-symbols-rounded agents-sidebar-row__icon" aria-hidden="true">smart_toy</span>
              <span className="agents-sidebar-row__copy">
                <strong>{agentType.name}</strong>
                <span>{agentType.role_id}</span>
              </span>
            </button>
          ))
        ) : (
          <p className="agents-sidebar-empty">No agents found.</p>
        )}
      </div>
    </main>
  );
}

function AgentsSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="agents-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="agents-sidebar-skeleton__row" key={index}>
          <span className="agents-sidebar-skeleton__icon" />
          <span className="agents-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('agents-sidebar-root') as HTMLElement).render(<AgentsSidebarWidget />);
