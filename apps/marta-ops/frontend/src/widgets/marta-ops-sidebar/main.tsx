import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Icon } from '../../Icon';
import {
  isMaverickParentMessage,
  mountedAppIdFromPath,
  openApp,
  postToShell,
  viewFromAppPage,
} from '../../lib/shellNavigation';
import type { ViewId } from '../../types';
import '../../styles/sidebar-widget.css';

const WIDGET_ID = 'marta-ops-sidebar';

const SECTIONS: Array<{
  id: ViewId;
  icon: 'today' | 'work' | 'ideas';
  label: string;
  note: string;
}> = [
  { id: 'today', icon: 'today', label: 'Oggi', note: 'Priorità e scadenze' },
  { id: 'work', icon: 'work', label: 'Lavori', note: 'Collaborazioni e consegne' },
  { id: 'ideas', icon: 'ideas', label: 'Idee', note: 'Inbox creativa' },
];

type WidgetContext = {
  content?: {
    payload?: {
      active_app_params?: Record<string, unknown>;
      is_mobile_layout?: boolean;
    };
  };
};

async function loadWidgetContext(signal: AbortSignal): Promise<WidgetContext> {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('context')
    || new URLSearchParams(window.location.search).get('context');
  if (!token) return {};
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) throw new Error('Contesto sidebar non disponibile.');
  return (await response.json()).context;
}

function MartaOpsSidebar() {
  const [activeView, setActiveView] = useState<ViewId>('today');
  const [isMobile, setIsMobile] = useState(false);
  const appId = useMemo(() => mountedAppIdFromPath(), []);

  useEffect(() => {
    const controller = new AbortController();
    let receivedLiveContext = false;

    function applyContext(context: WidgetContext) {
      const payload = context.content?.payload;
      const nextView = viewFromAppPage(payload?.active_app_params?.app_page);
      if (nextView) setActiveView(nextView);
      setIsMobile(payload?.is_mobile_layout === true);
    }

    function handleShellMessage(event: MessageEvent) {
      if (!isMaverickParentMessage(event)) return;
      const message = event.data as { context?: WidgetContext; type?: string };
      if (message.type !== 'maverick.widget.context-changed' || !message.context) return;
      receivedLiveContext = true;
      applyContext(message.context);
    }

    window.addEventListener('message', handleShellMessage);
    void loadWidgetContext(controller.signal)
      .then((context) => { if (!controller.signal.aborted && !receivedLiveContext) applyContext(context); })
      .catch(() => undefined);
    postToShell({ type: 'maverick.widget.ready', owner_app_id: appId, widget_id: WIDGET_ID });
    return () => {
      controller.abort();
      window.removeEventListener('message', handleShellMessage);
    };
  }, [appId]);

  function navigate(view: ViewId) {
    setActiveView(view);
    openApp(appId, { app_page: view });
    if (isMobile) postToShell({ type: 'maverick.shell.sidebar.close' });
  }

  return (
    <main className="marta-sidebar-widget">
      <p className="marta-sidebar-heading">Workspace</p>
      <nav aria-label="Marta Ops">
        {SECTIONS.map((section) => (
          <button
            aria-current={activeView === section.id ? 'page' : undefined}
            className={`marta-sidebar-row ${activeView === section.id ? 'is-active' : ''}`}
            key={section.id}
            onClick={() => navigate(section.id)}
            type="button"
          >
            <span className="marta-sidebar-row__icon"><Icon name={section.icon} size={18} /></span>
            <span className="marta-sidebar-row__copy">
              <strong>{section.label}</strong>
              <span>{section.note}</span>
            </span>
          </button>
        ))}
      </nav>
    </main>
  );
}

createRoot(document.getElementById('marta-ops-sidebar-root')!).render(<MartaOpsSidebar />);
