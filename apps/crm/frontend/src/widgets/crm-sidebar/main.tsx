import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Building2, CheckSquare, Contact, Gauge, Handshake, Search, StickyNote, Upload } from 'lucide-react';
import { BootstrapPayload, callBackend } from '../../api';
import './styles.css';

const nav = [
  { label: 'Dashboard', page: '', icon: Gauge },
  { label: 'Accounts', page: 'accounts', icon: Building2 },
  { label: 'Contacts', page: 'contacts', icon: Contact },
  { label: 'Deals', page: 'deals', icon: Handshake },
  { label: 'Tasks', page: 'tasks', icon: CheckSquare },
  { label: 'Notes', page: 'notes', icon: StickyNote },
  { label: 'Import', page: 'import', icon: Upload }
];

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

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

function openCrm(page = '') {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'crm',
      params: page ? { app_page: page } : {}
    },
    window.location.origin
  );
}

function CrmSidebar() {
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  async function refresh() {
    try {
      const payload = await callBackend<BootstrapPayload>({ action: 'bootstrap' });
      const viewFilter = payload.view_state?.view_filter;
      const nextQuery = viewFilter?.mode === 'search' && typeof viewFilter.query === 'string' ? viewFilter.query : '';
      lastPersistedQueryRef.current = nextQuery;
      hasLoadedViewStateRef.current = true;
      setQuery(nextQuery);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load CRM.');
    }
  }

  useEffect(() => {
    void refresh();
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      if (event.data.type === 'maverick.widget.data-changed' && event.data.owner_app_id === 'crm') {
        void refresh();
      }
      if (event.data.type === 'maverick.widget.context-changed') {
        void refresh();
      }
      if (event.data.type === 'maverick.app.visibility-changed' && event.data.visible) {
        void refresh();
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    if (!hasLoadedViewStateRef.current || query === lastPersistedQueryRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = query.trim();
      callBackend({ action: 'crm.set_view_filter', query: nextQuery, entity_type: 'all' })
        .then(() => {
          lastPersistedQueryRef.current = nextQuery;
          setError('');
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

  return (
    <main className={`crm-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="crm-sidebar-search-frame">
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search CRM"
          className="crm-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search CRM"
          value={query}
        />
      </div>

      <div className="crm-sidebar-list">
        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button className="crm-sidebar-row" key={item.label} onClick={() => openCrm(item.page)}>
                <Icon size={15} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
      {error ? <p className="crm-sidebar-error">{error}</p> : null}
    </main>
  );
}

createRoot(document.getElementById('crm-sidebar-root')!).render(<CrmSidebar />);
