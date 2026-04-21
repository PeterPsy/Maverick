import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "../../App";
import type { ChatThread, ProviderItem } from "../../api/client";
import { getRuntimeSession, listProviders, listThreads, selectProvider } from "../../api/client";
import { ProviderSelector } from "../../components/ProviderSelector";
import "../../styles/main.css";
import "./styles.css";

const EXPANDED_SIZE = {
  width: "min(25rem, calc(100vw - 2rem))",
  height: "min(38rem, calc(100dvh - 2rem))",
};

const COLLAPSED_SIZE = {
  width: "3rem",
  height: "3rem",
};

function postWidgetSize(isCollapsed: boolean) {
  const size = isCollapsed ? COLLAPSED_SIZE : EXPANDED_SIZE;
  window.parent?.postMessage(
    {
      ...size,
      type: "maverick.widget.resize",
      owner_app_id: "chat",
      widget_id: "chat-floating",
    },
    window.location.origin,
  );
}

function ChatFloatingMount() {
  const [activeThreadId, setActiveThreadId] = useState("");
  const [activeProviderId, setActiveProviderId] = useState("codex");
  const [executionMode, setExecutionMode] = useState("runtime");
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);

  useEffect(() => {
    postWidgetSize(isCollapsed);
  }, [isCollapsed]);

  useEffect(() => {
    void refreshProviders();
    void refreshThreads();

    function handleWidgetMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        owner_app_id?: string;
        resource?: string;
        type?: string;
      };
      if (payload.type !== "maverick.widget.data-changed" || payload.owner_app_id !== "chat" || payload.resource !== "threads") {
        return;
      }
      void refreshThreads(typeof payload.active_thread_id === "string" ? payload.active_thread_id : "");
    }

    window.addEventListener("message", handleWidgetMessage);
    return () => window.removeEventListener("message", handleWidgetMessage);
  }, []);

  async function refreshThreads(preferredThreadId = "") {
    try {
      const payload = await listThreads();
      const selectedThreadId =
        preferredThreadId || (activeThreadId && payload.threads.some((thread) => thread.thread_id === activeThreadId) ? activeThreadId : payload.threads[0]?.thread_id || "");
      setThreads(payload.threads);
      setActiveThreadId(selectedThreadId);
      void refreshExecutionMode(payload.threads.find((thread) => thread.thread_id === selectedThreadId) || null);
    } catch {
      setThreads([]);
      setActiveThreadId("");
      setExecutionMode("runtime");
    }
  }

  async function refreshProviders() {
    try {
      const payload = await listProviders();
      setProviders(payload.items || [payload.active_provider]);
      setActiveProviderId(payload.active_provider.provider_id);
    } catch {
      setProviders([]);
    }
  }

  async function refreshExecutionMode(thread: ChatThread | null) {
    if (!thread?.runtime_session_id) {
      setExecutionMode("runtime");
      return;
    }
    try {
      const session = await getRuntimeSession(thread.runtime_session_id);
      setExecutionMode(session.effective_mode || "runtime");
    } catch {
      setExecutionMode("runtime");
    }
  }

  function navigateChat(params: Record<string, string | boolean | null>) {
    window.postMessage({ type: "maverick.app.navigate", app_id: "chat", params }, window.location.origin);
  }

  function handleThreadChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const threadId = event.target.value;
    setActiveThreadId(threadId);
    if (threadId) {
      void refreshExecutionMode(threads.find((thread) => thread.thread_id === threadId) || null);
      navigateChat({ thread_id: threadId });
    }
  }

  async function handleProviderSelect(providerId: string) {
    setActiveProviderId(providerId);
    try {
      const payload = await selectProvider(providerId);
      setActiveProviderId(payload.active_provider.provider_id);
    } catch {
      void refreshProviders();
    }
  }

  function handleNewChat() {
    navigateChat({ new_chat: true, new_chat_request_id: crypto.randomUUID() });
  }

  if (isCollapsed) {
    return (
      <button aria-label="Apri chat" className="chat-floating-widget-launcher" onClick={() => setIsCollapsed(false)} type="button">
        <span aria-hidden="true" className="material-symbols-rounded">
          forum
        </span>
      </button>
    );
  }

  return (
    <section className="chat-floating-widget-shell" aria-label="Chat">
      <header className="chat-floating-widget-shell__bar">
        <div className="chat-floating-widget-shell__thread-tools">
          <label className="chat-floating-widget-shell__thread-picker">
            <select aria-label="Scegli chat" disabled={threads.length === 0} onChange={handleThreadChange} value={activeThreadId}>
              {threads.length === 0 ? <option value="">New chat</option> : null}
              {threads.map((thread) => (
                <option key={thread.thread_id} value={thread.thread_id}>
                  {thread.title || "New chat"}
                </option>
              ))}
            </select>
          </label>
          <button aria-label="Nuova chat" className="chat-floating-widget-shell__button" onClick={handleNewChat} type="button">
            <span aria-hidden="true" className="material-symbols-rounded">
              add
            </span>
          </button>
        </div>
        <div className="chat-floating-widget-shell__runtime-tools">
          <ProviderSelector activeProviderId={activeProviderId} disabled={providers.length === 0} onSelect={handleProviderSelect} providers={providers} />
          <span
            aria-label={executionMode}
            className={`chat-floating-widget-shell__mode-icon ${executionMode === "full-access" ? "is-full-access" : "is-sandbox"}`}
            role="img"
            title={executionMode}
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              {executionMode === "full-access" ? "admin_panel_settings" : "lock"}
            </span>
          </span>
        </div>
        <button aria-label="Collassa chat" className="chat-floating-widget-shell__button" onClick={() => setIsCollapsed(true)} type="button">
          <span aria-hidden="true" className="material-symbols-rounded">
            keyboard_arrow_down
          </span>
        </button>
      </header>
      <div className="chat-floating-widget-shell__body">
        <App enablePageCapture />
      </div>
    </section>
  );
}

postWidgetSize(false);

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ChatFloatingMount />
  </React.StrictMode>,
);
