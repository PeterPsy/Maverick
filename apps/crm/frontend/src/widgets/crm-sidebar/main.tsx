import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BarChart3, Handshake, Rows3 } from 'lucide-react';
import './styles.css';

const nav = [
  { label: 'Records', page: 'records', icon: Rows3 },
  { label: 'Pipeline', page: 'pipeline', icon: Handshake },
  { label: 'Reports', page: 'reports', icon: BarChart3 }
];

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

type WidgetContext = {
  content?: {
    payload?: {
      active_app_params?: Record<string, unknown>;
      is_mobile_layout?: boolean;
    };
  };
};

function contextToken() {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get('context') || new URLSearchParams(window.location.search).get('context') || '';
}

async function loadWidgetContext(): Promise<WidgetContext> {
  const token = contextToken();
  if (!token) {
    return {};
  }
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) {
    return {};
  }
  return (await response.json()).context as WidgetContext;
}

function activePageFromContext(context: WidgetContext) {
  const appPage = context.content?.payload?.active_app_params?.app_page;
  return activePageFromAppPage(typeof appPage === 'string' ? appPage : '');
}

function activePageFromAppPage(appPage: string) {
  const [segment] = appPage.split('/').filter(Boolean);
  const route = segment || 'records';
  if (route === 'reports') return 'reports';
  if (route === 'pipeline' || route === 'operations' || route === 'tasks' || route === 'notes' || route === 'activities') return 'pipeline';
  return 'records';
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
    "*"
  );
}

function CrmSidebar() {
  const isShellMobileLayout = useShellMobileLayout();
  const [activePage, setActivePage] = useState('records');

  useEffect(() => {
    loadWidgetContext().then((context) => {
      setActivePage(activePageFromContext(context));
    });
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { context?: WidgetContext; type?: string };
      if (payload.type === 'maverick.widget.context-changed' && payload.context) {
        setActivePage(activePageFromContext(payload.context));
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  return (
    <main className={`crm-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="crm-sidebar-list">
        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            const isActive = activePage === item.page;
            return (
              <button
                className={`crm-sidebar-row ${isActive ? 'is-active' : ''}`}
                key={item.label}
                onClick={() => {
                  setActivePage(item.page);
                  openCrm(item.page);
                }}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon size={15} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </main>
  );
}

createRoot(document.getElementById('crm-sidebar-root')!).render(<CrmSidebar />);
