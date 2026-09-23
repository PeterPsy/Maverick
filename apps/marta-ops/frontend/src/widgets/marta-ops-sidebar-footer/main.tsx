import { useEffect, useMemo } from 'react';
import { createRoot } from 'react-dom/client';
import { mountedAppIdFromPath, openApp, postToShell, isMaverickParentMessage } from '../../lib/shellNavigation';
import '../../styles/sidebar-widget.css';

const WIDGET_ID = 'marta-ops-sidebar-footer';
const ACTION_LABEL = 'Nuovo lavoro';

function openNewWork(appId: string) {
  openApp(appId, {
    app_page: 'work',
    new_work: true,
    new_work_request_id: crypto.randomUUID(),
  });
}

function postActionState(appId: string) {
  postToShell({
    type: 'maverick.widget.primary-action.state',
    owner_app_id: appId,
    widget_id: WIDGET_ID,
    available: true,
    label: ACTION_LABEL,
  });
}

function MartaOpsSidebarFooter() {
  const appId = useMemo(() => mountedAppIdFromPath(), []);

  useEffect(() => {
    postActionState(appId);
    function handleShellMessage(event: MessageEvent) {
      if (!isMaverickParentMessage(event)) return;
      const message = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      if (message.owner_app_id !== appId || message.widget_id !== WIDGET_ID) return;
      if (message.type === 'maverick.widget.primary-action.query') postActionState(appId);
      if (message.type === 'maverick.widget.primary-action.invoke') openNewWork(appId);
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  return (
    <main className="marta-sidebar-footer-widget">
      <button className="marta-sidebar-footer-button" onClick={() => openNewWork(appId)} type="button">
        <span aria-hidden="true" className="marta-sidebar-footer-plus" />
        <span>{ACTION_LABEL}</span>
      </button>
    </main>
  );
}

createRoot(document.getElementById('marta-ops-sidebar-footer-root')!).render(<MartaOpsSidebarFooter />);
