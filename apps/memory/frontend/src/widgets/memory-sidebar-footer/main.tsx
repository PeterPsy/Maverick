import { createRoot } from "react-dom/client";
import { Plus } from "lucide-react";
import "../../styles/sidebar-widget.css";

function createNodeInShell() {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: "memory",
      params: {
        new_node: true,
        new_node_request_id: crypto.randomUUID(),
      },
    },
    window.location.origin,
  );
}

function MemorySidebarFooterWidget() {
  return (
    <main className="memory-sidebar-footer-widget">
      <button className="memory-sidebar-footer-button" onClick={createNodeInShell} type="button">
        <Plus size={16} aria-hidden="true" />
        <span>Create</span>
      </button>
    </main>
  );
}

createRoot(document.getElementById("memory-sidebar-footer-root") as HTMLElement).render(<MemorySidebarFooterWidget />);
