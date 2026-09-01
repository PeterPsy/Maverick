import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { Plus } from 'lucide-react';
import '../../styles/sidebar-widget.css';

const DEFAULT_APP_ID = 'skills';
const PRIMARY_ACTION_LABEL = 'New Skill';
const WIDGET_ID = 'skills-sidebar-footer';

function createSkillInShell(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        new_skill: true,
        new_skill_request_id: crypto.randomUUID()
      }
    },
    "*"
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
    "*"
  );
}

function SkillsSidebarFooterWidget() {
  const appId = currentSkillsAppId();

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
        createSkillInShell(appId);
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  return (
    <main className="skills-sidebar-footer-widget">
      <button className="skills-sidebar-footer-button" onClick={() => createSkillInShell(appId)} type="button">
        <Plus size={16} aria-hidden="true" />
        <span>New Skill</span>
      </button>
    </main>
  );
}

function currentSkillsAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
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

createRoot(document.getElementById('skills-sidebar-footer-root') as HTMLElement).render(<SkillsSidebarFooterWidget />);
