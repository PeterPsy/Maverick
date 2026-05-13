import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import '../../styles/sidebar-widget.css';

const DEFAULT_APP_ID = 'agents';
const PRIMARY_ACTION_LABEL = 'New Agent';
const WIDGET_ID = 'agents-sidebar-footer';

function createAgentInShell(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        new_agent: true,
        new_agent_request_id: crypto.randomUUID()
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

function AgentsSidebarFooterWidget() {
  const appId = currentAgentsAppId();

  useEffect(() => {
    postPrimaryActionState(appId);
    function handleShellMessage(event: MessageEvent) {
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
        createAgentInShell(appId);
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  return (
    <main className="agents-sidebar-footer-widget">
      <button className="agents-sidebar-footer-button" onClick={() => createAgentInShell(appId)} type="button">
        <span aria-hidden="true" className="agents-sidebar-footer-plus" />
        <span>New Agent</span>
      </button>
    </main>
  );
}

function currentAgentsAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
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

createRoot(document.getElementById('agents-sidebar-footer-root') as HTMLElement).render(<AgentsSidebarFooterWidget />);
