import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { ChatThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import "./styles.css";

const DEFAULT_APP_ID = "chat";
const PRIMARY_ACTION_LABEL = "New chat";
const WIDGET_ID = "chat-sidebar-footer";

function notifyShell(appId: string, projectId: string | null) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: appId,
      params: {
        new_chat: true,
        new_chat_request_id: crypto.randomUUID(),
        project_id: projectId,
      },
    },
    window.location.origin,
  );
}

function postPrimaryActionState(appId: string, available: boolean) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.primary-action.state",
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available,
      label: PRIMARY_ACTION_LABEL,
    },
    window.location.origin,
  );
}

function ChatSidebarFooterWidget() {
  const appId = currentChatAppId();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [, setError] = useState<string | null>(null);

  useRuntimeThreads({ onSnapshot: () => setIsInitialLoading(false), setError, setThreads });

  useEffect(() => {
    postPrimaryActionState(appId, !isInitialLoading);
  }, [appId, isInitialLoading]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        owner_app_id?: string;
        type?: string;
        widget_id?: string;
      };
      if (
        payload.owner_app_id === appId &&
        payload.widget_id === WIDGET_ID &&
        payload.type === "maverick.widget.primary-action.query"
      ) {
        postPrimaryActionState(appId, !isInitialLoading);
        return;
      }
      if (
        payload.owner_app_id === appId &&
        payload.widget_id === WIDGET_ID &&
        payload.type === "maverick.widget.primary-action.invoke"
      ) {
        if (!isInitialLoading) {
          createChatInCurrentContext();
        }
        return;
      }
      if (
        (payload.type === "maverick.chat.active-thread-changed" || payload.type === "maverick.widget.data-changed") &&
        payload.owner_app_id === appId
      ) {
        setActiveThreadId(payload.active_thread_id || null);
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [activeThreadId, appId, isInitialLoading, threads]);

  function createChatInCurrentContext() {
    const activeThread = activeThreadId ? threads.find((thread) => thread.thread_id === activeThreadId) : undefined;
    notifyShell(appId, activeThread?.project_id || null);
  }

  return (
    <main className="bs-chat-sidebar-footer-widget">
      <button
        aria-label="New chat"
        className="bs-chat-sidebar-footer__new-chat"
        disabled={isInitialLoading}
        onClick={createChatInCurrentContext}
        type="button"
      >
        <span aria-hidden="true" className="bs-chat-sidebar-footer__plus" />
        <span>New chat</span>
      </button>
    </main>
  );
}

function currentChatAppId(pathname = typeof window === "undefined" ? "" : window.location.pathname): string {
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

createRoot(document.getElementById("chat-sidebar-footer-root") as HTMLElement).render(<ChatSidebarFooterWidget />);
