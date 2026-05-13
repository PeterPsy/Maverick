import { createRoot } from 'react-dom/client';
import { ListChecks } from 'lucide-react';
import '../../styles/sidebar-widget.css';

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

function openChecklistInShell() {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'checklist',
      params: {
        app_page: 'agent-plans'
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function ChecklistSidebarFooterWidget() {
  return (
    <main className="checklist-sidebar-footer-widget">
      <button className="checklist-sidebar-footer-button" onClick={openChecklistInShell} type="button">
        <ListChecks size={16} aria-hidden="true" />
        <span>Agent Plans</span>
      </button>
    </main>
  );
}

createRoot(document.getElementById('checklist-sidebar-footer-root') as HTMLElement).render(<ChecklistSidebarFooterWidget />);
