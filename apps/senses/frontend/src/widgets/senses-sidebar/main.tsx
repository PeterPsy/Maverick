import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';
const TABS = [
  { id: 'devices', label: 'Devices', summary: 'Registered sensors and glasses', icon: 'sensors' },
  { id: 'pairing', label: 'Pairing', summary: 'Pair phones and glasses', icon: 'key' },
  { id: 'captures', label: 'Captures', summary: 'Stored sensor inputs', icon: 'photo_camera' },
  { id: 'routing', label: 'Routing', summary: 'Chat handoff sessions', icon: 'route' },
  { id: 'settings', label: 'Settings', summary: 'Workspace policies', icon: 'tune' },
  { id: 'debug', label: 'Debug', summary: 'Diagnostics and queues', icon: 'bug_report' },
] as const;

type TabId = (typeof TABS)[number]['id'];

function initialTab(): TabId {
  return tabFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())) || 'devices';
}

function SensesSidebarWidget() {
  const [query, setQuery] = useState('');
  const [selectedTab, setSelectedTab] = useState<TabId>(initialTab);

  const filteredTabs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return TABS;
    }
    return TABS.filter((tab) => `${tab.label} ${tab.summary} ${tab.id}`.toLowerCase().includes(needle));
  }, [query]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        context?: { content?: { payload?: unknown } };
        owner_app_id?: string;
        selection?: Record<string, unknown>;
        type?: string;
      };
      if (payload.type === 'maverick.widget.context-changed') {
        const tab = tabFromParams(activeAppParamsFromContext(payload.context?.content?.payload));
        if (tab) {
          setSelectedTab(tab);
        }
        return;
      }
      if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'senses') {
        const tab = tabFromParams(payload.selection || {});
        if (tab) {
          setSelectedTab(tab);
        }
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function openTab(tab: TabId) {
    setSelectedTab(tab);
    window.parent?.postMessage(
      {
        type: 'maverick.widget.open-app',
        app_id: 'senses',
        params: {
          app_page: tab,
          tab,
        },
      },
      "*",
    );
    if (isMobileLayoutViewport()) {
      window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, "*");
    }
  }

  return (
    <main className={`senses-sidebar-widget ${isMobileLayoutViewport() ? 'is-shell-mobile' : ''}`}>
      <div className="senses-sidebar-search-frame">
        <span className="material-symbols-rounded" aria-hidden="true">search</span>
        <input
          aria-label="Search Senses sections"
          className="senses-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search sections"
          value={query}
        />
      </div>

      <div className="senses-sidebar-list">
        {filteredTabs.length ? (
          filteredTabs.map((tab) => (
            <button
              className={`senses-sidebar-row ${tab.id === selectedTab ? 'is-active' : ''}`}
              key={tab.id}
              onClick={() => openTab(tab.id)}
              type="button"
            >
              <span className="material-symbols-rounded senses-sidebar-row__icon" aria-hidden="true">{tab.icon}</span>
              <span className="senses-sidebar-row__copy">
                <strong>{tab.label}</strong>
                <span>{tab.summary}</span>
              </span>
            </button>
          ))
        ) : (
          <p className="senses-sidebar-empty">No sections found.</p>
        )}
      </div>
    </main>
  );
}

function activeAppParamsFromContext(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return {};
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  return activeAppParams && typeof activeAppParams === 'object' && !Array.isArray(activeAppParams)
    ? activeAppParams as Record<string, unknown>
    : {};
}

function tabFromParams(params: Record<string, unknown>): TabId | null {
  const directTab = scalarString(params.tab || params.page_id || params.view || params.section);
  if (isTabId(directTab)) {
    return directTab;
  }
  const appPage = scalarString(params.app_page);
  if (!appPage) {
    return null;
  }
  const firstSegment = appPage.split('/')[0]?.trim();
  return isTabId(firstSegment) ? firstSegment : null;
}

function isTabId(value: string): value is TabId {
  return TABS.some((tab) => tab.id === value);
}

function scalarString(value: unknown): string {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value).trim();
  }
  return '';
}

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

createRoot(document.getElementById('senses-sidebar-root') as HTMLElement).render(<SensesSidebarWidget />);
