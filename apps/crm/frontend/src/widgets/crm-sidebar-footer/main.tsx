import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { Plus } from 'lucide-react';
import './styles.css';

const DEFAULT_APP_ID = 'crm';
const PRIMARY_ACTION_LABEL = 'Add';
const WIDGET_ID = 'crm-sidebar-footer';

function openCreateMenu(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        intent: 'create-menu',
        create_menu_request_id: crypto.randomUUID()
      }
    },
    window.location.origin
  );
}

function postPrimaryActionState(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.primary-action.state',
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available: true,
      label: PRIMARY_ACTION_LABEL
    },
    window.location.origin
  );
}

function CrmSidebarFooter() {
  const appId = currentCrmAppId();
  useEffect(() => {
    postPrimaryActionState(appId);
  }, [appId]);

  useEffect(() => {
    function handlePrimaryActionMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      if (payload.owner_app_id !== appId || payload.widget_id !== WIDGET_ID) {
        return;
      }
      if (payload.type === 'maverick.widget.primary-action.query') {
        postPrimaryActionState(appId);
        return;
      }
      if (payload.type === 'maverick.widget.primary-action.invoke') {
        openCreateMenu(appId);
      }
    }
    window.addEventListener('message', handlePrimaryActionMessage);
    return () => window.removeEventListener('message', handlePrimaryActionMessage);
  }, [appId]);

  return (
    <main className="crm-sidebar-footer-widget">
      <button className="crm-add-button" type="button" onClick={() => openCreateMenu(appId)}>
        <Plus size={17} aria-hidden="true" />
        <span>Add</span>
      </button>
    </main>
  );
}

function currentCrmAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
  return mountedAppIdFromPath(pathname, DEFAULT_APP_ID);
}

function mountedAppIdFromPath(pathname: string, fallback: string): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return fallback;
  }
  try {
    return decodeURIComponent(match[1]) || fallback;
  } catch {
    return match[1] || fallback;
  }
}

createRoot(document.getElementById('crm-sidebar-footer-root')!).render(<CrmSidebarFooter />);
