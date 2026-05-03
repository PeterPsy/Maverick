import { createRoot } from 'react-dom/client';
import '../../styles/sidebar-widget.css';

function createAgentInShell() {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'agents',
      params: {
        new_agent: true,
        new_agent_request_id: crypto.randomUUID()
      }
    },
    window.location.origin
  );
}

function AgentsSidebarFooterWidget() {
  return (
    <main className="agents-sidebar-footer-widget">
      <button className="agents-sidebar-footer-button" onClick={createAgentInShell} type="button">
        <span aria-hidden="true" className="agents-sidebar-footer-plus" />
        <span>New Agent</span>
      </button>
    </main>
  );
}

createRoot(document.getElementById('agents-sidebar-footer-root') as HTMLElement).render(<AgentsSidebarFooterWidget />);
