import { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { Eye, Plus } from "lucide-react";
import { currentMemoryAppId } from "../../memoryApi";
import "../../styles/sidebar-widget.css";

const PRIMARY_ACTION_LABEL = "Create node";

function createNodeInShell(appId: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: appId,
      params: {
        new_node: true,
        new_node_request_id: crypto.randomUUID(),
      },
    },
    window.location.origin,
  );
}

function postPrimaryActionState(appId: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.primary-action.state",
      owner_app_id: appId,
      widget_id: "memory-sidebar-footer",
      available: true,
      label: PRIMARY_ACTION_LABEL,
    },
    window.location.origin,
  );
}

function previewContextInShell(appId: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: appId,
      params: {
        preview_context: true,
        preview_context_request_id: crypto.randomUUID(),
      },
    },
    window.location.origin,
  );
}

function MemorySidebarFooterWidget() {
  const appId = currentMemoryAppId();

  useEffect(() => {
    postPrimaryActionState(appId);
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      if (payload.owner_app_id !== appId || payload.widget_id !== "memory-sidebar-footer") {
        return;
      }
      if (payload.type === "maverick.widget.primary-action.query") {
        postPrimaryActionState(appId);
        return;
      }
      if (payload.type === "maverick.widget.primary-action.invoke") {
        createNodeInShell(appId);
      }
    }
    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [appId]);

  return (
    <main className="memory-sidebar-footer-widget">
      <div className="memory-sidebar-footer-actions">
        <button
          className="memory-sidebar-footer-button memory-sidebar-footer-button--context"
          onClick={() => previewContextInShell(appId)}
          type="button"
        >
          <Eye size={15} aria-hidden="true" />
          <span>Preview context</span>
        </button>
        <button
          aria-label="Create node"
          className="memory-sidebar-footer-button memory-sidebar-footer-button--icon"
          onClick={() => createNodeInShell(appId)}
          title="Create node"
          type="button"
        >
          <Plus size={17} aria-hidden="true" />
        </button>
      </div>
    </main>
  );
}

createRoot(document.getElementById("memory-sidebar-footer-root") as HTMLElement).render(<MemorySidebarFooterWidget />);
