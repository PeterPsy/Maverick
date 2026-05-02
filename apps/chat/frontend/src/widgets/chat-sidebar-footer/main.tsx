import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { ChatThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import "./styles.css";

function notifyShell(projectId: string | null) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: "chat",
      params: {
        new_chat: true,
        new_chat_request_id: crypto.randomUUID(),
        project_id: projectId,
      },
    },
    window.location.origin,
  );
}

function ChatSidebarFooterWidget() {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [, setError] = useState<string | null>(null);

  useRuntimeThreads({ onSnapshot: () => setIsInitialLoading(false), setError, setThreads });

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        owner_app_id?: string;
        type?: string;
      };
      if (
        (payload.type === "maverick.chat.active-thread-changed" || payload.type === "maverick.widget.data-changed") &&
        payload.owner_app_id === "chat"
      ) {
        setActiveThreadId(payload.active_thread_id || null);
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, []);

  function createChatInCurrentContext() {
    const activeThread = activeThreadId ? threads.find((thread) => thread.thread_id === activeThreadId) : undefined;
    notifyShell(activeThread?.project_id || null);
  }

  return (
    <main className="bs-chat-sidebar-footer-widget">
      <button
        aria-label="Nuova chat"
        className="bs-chat-sidebar-footer__new-chat"
        disabled={isInitialLoading}
        onClick={createChatInCurrentContext}
        type="button"
      >
        <span aria-hidden="true" className="bs-chat-sidebar-footer__plus" />
        <span>Nuova chat</span>
      </button>
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-footer-root") as HTMLElement).render(<ChatSidebarFooterWidget />);
