import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "../../App";
import type { ChatThread, ProviderItem } from "../../api/client";
import { getRuntimeSession, listProviders, listThreads, selectProvider } from "../../api/client";
import { ProviderSelector } from "../../components/ProviderSelector";
import { withRuntimeAvailability } from "../chat-sidebar/runtimeStatus";
import { isThreadBusy } from "../chat-sidebar/sections";
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
  const [isThreadMenuOpen, setIsThreadMenuOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const threadMenuRef = useRef<HTMLDivElement | null>(null);
  const activeThread = threads.find((thread) => thread.thread_id === activeThreadId) || null;

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

  useEffect(() => {
    if (!isThreadMenuOpen) {
      return;
    }
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || threadMenuRef.current?.contains(target)) {
        return;
      }
      setIsThreadMenuOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsThreadMenuOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isThreadMenuOpen]);

  async function refreshThreads(preferredThreadId = "") {
    try {
      const payload = await listThreads();
      const hydratedThreads = await withRuntimeAvailability(payload.threads || []);
      const selectedThreadId =
        preferredThreadId || (activeThreadId && hydratedThreads.some((thread) => thread.thread_id === activeThreadId) ? activeThreadId : hydratedThreads[0]?.thread_id || "");
      setThreads(hydratedThreads);
      setActiveThreadId(selectedThreadId);
      void refreshExecutionMode(hydratedThreads.find((thread) => thread.thread_id === selectedThreadId) || null);
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

  function selectThread(threadId: string) {
    setActiveThreadId(threadId);
    setIsThreadMenuOpen(false);
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

  return (
    <>
      <button
        aria-label="Apri chat"
        className={`chat-floating-widget-launcher ${isCollapsed ? "" : "is-hidden"}`}
        onClick={() => setIsCollapsed(false)}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          forum
        </span>
      </button>
      <section className={`chat-floating-widget-shell ${isCollapsed ? "is-hidden" : ""}`} aria-label="Chat">
      <header className="chat-floating-widget-shell__bar">
        <div className="chat-floating-widget-shell__thread-tools">
          <div className="chat-floating-thread-menu" ref={threadMenuRef}>
            <button
              aria-expanded={isThreadMenuOpen}
              aria-haspopup="menu"
              aria-label="Scegli chat"
              className={`chat-floating-thread-menu__trigger ${activeThread && isThreadBusy(activeThread) ? "is-busy" : ""}`}
              disabled={threads.length === 0}
              onClick={() => setIsThreadMenuOpen((current) => !current)}
              type="button"
            >
              <span className="chat-floating-thread-menu__trigger-title">{activeThread?.title || "New chat"}</span>
              {activeThread && isThreadBusy(activeThread) ? <span aria-label="Chat in lavoro" className="chat-floating-thread-menu__presence" title="Chat in lavoro" /> : null}
              <span aria-hidden="true" className="material-symbols-rounded chat-floating-thread-menu__chevron">
                expand_more
              </span>
            </button>
            {isThreadMenuOpen ? (
              <div className="chat-floating-thread-menu__panel" role="menu">
                {threads.map((thread) => {
                  const isBusy = isThreadBusy(thread);
                  return (
                    <button
                      className={`chat-floating-thread-menu__item ${activeThreadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""}`}
                      key={thread.thread_id}
                      onClick={() => selectThread(thread.thread_id)}
                      role="menuitem"
                      type="button"
                    >
                      <span className="chat-floating-thread-menu__item-copy">
                        <span className="chat-floating-thread-menu__item-title">{thread.title || "New chat"}</span>
                      </span>
                      {isBusy ? <span aria-label="Chat in lavoro" className="chat-floating-thread-menu__presence is-busy" title="Chat in lavoro" /> : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
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
    </>
  );
}

postWidgetSize(false);

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ChatFloatingMount />
  </React.StrictMode>,
);
