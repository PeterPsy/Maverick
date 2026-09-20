import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { viewFromAppPage } from '../../domain/routing';
import { postToShell } from '../../domain/shellMessaging';
import { ViewId } from '../../domain/types';
import { useLiveCrm } from '../../domain/vnext';
import { WorkspaceSidebar } from './WorkspaceSidebar';
import './styles.css';

type WidgetContext = {
  content?: { payload?: { active_app_params?: Record<string, unknown>; is_mobile_layout?: boolean } };
};

async function loadWidgetContext(signal: AbortSignal): Promise<WidgetContext> {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('context')
    || new URLSearchParams(window.location.search).get('context');
  if (!token) return {};
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    signal, credentials: 'same-origin', headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error('Widget context unavailable.');
  return (await response.json()).context;
}

function CrmSidebar() {
  const [activePage, setActivePage] = useState<ViewId>('overview');
  const [isShellMobile, setIsShellMobile] = useState(false);
  const counts = useLiveCrm<{ counts: Record<string, number> }>({ action: 'crm.workspace_view', view: 'sidebar' });

  useEffect(() => {
    const controller = new AbortController();
    let receivedContext = false;
    function applyContext(context: WidgetContext) {
      const payload = context.content?.payload;
      const appPage = payload?.active_app_params?.app_page;
      setActivePage(viewFromAppPage(typeof appPage === 'string' ? appPage : '').view);
      // The iframe width is not the shell viewport, especially on isolated origins.
      setIsShellMobile(payload?.is_mobile_layout === true);
    }
    function handleMessage(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event)) return;
      if (event.data?.type === 'maverick.widget.context-changed' && event.data.context) {
        receivedContext = true;
        applyContext(event.data.context);
      }
    }
    window.addEventListener('message', handleMessage);
    void loadWidgetContext(controller.signal).then((context) => {
      // A slow initial token response must not undo a newer navigation/context.
      if (!controller.signal.aborted && !receivedContext) applyContext(context);
    }).catch(() => undefined); // Ready handshake also supplies the current context.
    postToShell({ type: 'maverick.widget.ready', owner_app_id: 'crm', widget_id: 'crm-sidebar' });
    return () => { controller.abort(); window.removeEventListener('message', handleMessage); };
  }, []);

  function navigate(page: ViewId) {
    postToShell({ type: 'maverick.widget.open-app', app_id: 'crm', params: { app_page: page } });
  }

  return <main className={`crm-sidebar-widget ${isShellMobile ? 'is-shell-mobile' : ''}`}>
    <WorkspaceSidebar view={activePage} navigate={navigate} counts={counts.error ? {} : counts.data?.counts || {}} countsError={Boolean(counts.error)} retry={counts.refresh} />
  </main>;
}

createRoot(document.getElementById('crm-sidebar-root')!).render(<CrmSidebar />);
