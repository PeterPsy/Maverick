import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "../../App";
import type { ChatThread } from "../../api/client";
import { deleteThread, getRuntimeSession, getWidgetContext, listThreads, updateThread } from "../../api/client";
import { withRuntimeAvailability } from "../chat-sidebar/runtimeStatus";
import { isThreadBusy } from "../chat-sidebar/sections";
import "../../styles/main.css";
import "./styles.css";

const EXPANDED_HEIGHT = "min(38rem, calc(100dvh - 2rem))";
const EXPANDED_WIDTH_REM = 25;
const COLLAPSED_WIDTH_REM = 3;
const WINDOW_GAP_REM = 0.75;
const WIDGET_STATE_STORAGE_KEY_PREFIX = "maverick.chat.floating-widget.state.v1";
const FALLBACK_WIDGET_STATE_STORAGE_KEY = `${WIDGET_STATE_STORAGE_KEY_PREFIX}:global`;
const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";

type ChatWindow = {
  executionMode: string;
  id: string;
  isCollapsed: boolean;
  threadId: string;
};

type PersistedChatWindow = {
  id: string;
  isCollapsed: boolean;
  threadId: string;
};

type PersistedWidgetState = {
  version: 1;
  windows: PersistedChatWindow[];
};

function createWindow(threadId = ""): ChatWindow {
  return {
    executionMode: "runtime",
    id: `window-${crypto.randomUUID()}`,
    isCollapsed: false,
    threadId,
  };
}

function windowFromPersistedState(windowItem: PersistedChatWindow): ChatWindow {
  return {
    executionMode: "runtime",
    id: windowItem.id,
    isCollapsed: windowItem.isCollapsed,
    threadId: windowItem.threadId,
  };
}

function widgetStateStorageKey(workspaceId: string) {
  return `${WIDGET_STATE_STORAGE_KEY_PREFIX}:${workspaceId}`;
}

function readPersistedWindowsFromKey(storageKey: string): ChatWindow[] | null {
  try {
    const rawValue = window.localStorage.getItem(storageKey);
    if (!rawValue) {
      return null;
    }
    const payload = JSON.parse(rawValue) as Partial<PersistedWidgetState>;
    if (payload.version !== 1 || !Array.isArray(payload.windows) || payload.windows.length === 0) {
      return null;
    }
    const windows = payload.windows
      .map((windowItem) => {
        if (!windowItem || typeof windowItem !== "object") {
          return null;
        }
        const id = typeof windowItem.id === "string" && windowItem.id ? windowItem.id : "";
        if (!id) {
          return null;
        }
        return windowFromPersistedState({
          id,
          isCollapsed: windowItem.isCollapsed === true,
          threadId: typeof windowItem.threadId === "string" ? windowItem.threadId : "",
        });
      })
      .filter((windowItem): windowItem is ChatWindow => Boolean(windowItem));
    return windows.length > 0 ? windows : null;
  } catch {
    return null;
  }
}

function readPersistedWindows(storageKey = FALLBACK_WIDGET_STATE_STORAGE_KEY): ChatWindow[] {
  return readPersistedWindowsFromKey(storageKey) || [createWindow()];
}

function persistWindows(storageKey: string, windows: ChatWindow[]) {
  try {
    const payload: PersistedWidgetState = {
      version: 1,
      windows: windows.map((windowItem) => ({
        id: windowItem.id,
        isCollapsed: windowItem.isCollapsed,
        threadId: windowItem.threadId,
      })),
    };
    window.localStorage.setItem(storageKey, JSON.stringify(payload));
  } catch {
    // Persistence is best-effort UI state; runtime behavior must keep working.
  }
}

async function loadWidgetStateStorageKey(): Promise<string> {
  const token = new URLSearchParams(window.location.search).get("context");
  if (!token) {
    return FALLBACK_WIDGET_STATE_STORAGE_KEY;
  }
  try {
    const payload = await getWidgetContext(token);
    const content = payload.context.content;
    if (!content || typeof content !== "object") {
      return FALLBACK_WIDGET_STATE_STORAGE_KEY;
    }
    const workspaceId = (content as { workspace_id?: unknown }).workspace_id;
    return typeof workspaceId === "string" && workspaceId.trim() ? widgetStateStorageKey(workspaceId.trim()) : FALLBACK_WIDGET_STATE_STORAGE_KEY;
  } catch {
    return FALLBACK_WIDGET_STATE_STORAGE_KEY;
  }
}

function widgetSize(windows: ChatWindow[]) {
  const expandedCount = windows.filter((windowItem) => !windowItem.isCollapsed).length;
  const collapsedCount = windows.length - expandedCount;
  const gapCount = Math.max(0, windows.length - 1);
  const width = `min(calc(${expandedCount * EXPANDED_WIDTH_REM + collapsedCount * COLLAPSED_WIDTH_REM + gapCount * WINDOW_GAP_REM}rem), calc(100vw - 2rem))`;
  return {
    height: expandedCount > 0 ? EXPANDED_HEIGHT : "3rem",
    width,
  };
}

function postWidgetSize(windows: ChatWindow[]) {
  window.parent?.postMessage(
    {
      ...widgetSize(windows),
      type: "maverick.widget.resize",
      owner_app_id: "chat",
      widget_id: "chat-floating",
    },
    window.location.origin,
  );
}

function debugThreadSync(label: string, detail: Record<string, unknown> = {}) {
  try {
    if (window.localStorage.getItem(THREAD_SYNC_DEBUG_STORAGE_KEY) !== "1") {
      return;
    }
    console.debug(`[chat-widget thread-sync] ${label}`, {
      at: new Date().toISOString(),
      ...detail,
    });
  } catch {
    // Debug logging must never affect widget behavior.
  }
}

function ChatFloatingMount() {
  const [storageKey, setStorageKey] = useState(FALLBACK_WIDGET_STATE_STORAGE_KEY);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [windows, setWindows] = useState<ChatWindow[]>(readPersistedWindows);
  const pendingNewChatPreviousThreadByWindow = useRef<Map<string, string>>(new Map());
  const refreshThreadsRequestIdsByScopeRef = useRef<Map<string, number>>(new Map());
  const windowsRef = useRef(windows);

  useEffect(() => {
    windowsRef.current = windows;
    postWidgetSize(windows);
    persistWindows(storageKey, windows);
  }, [storageKey, windows]);

  useEffect(() => {
    let cancelled = false;
    async function loadScopedWidgetState() {
      const nextStorageKey = await loadWidgetStateStorageKey();
      if (cancelled || nextStorageKey === storageKey) {
        return;
      }
      setStorageKey(nextStorageKey);
      const persistedWindows = readPersistedWindowsFromKey(nextStorageKey);
      if (persistedWindows) {
        setWindows(persistedWindows);
      }
    }

    void loadScopedWidgetState();
    void refreshThreads();

    function handleWidgetMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        navigation_scope?: string;
        owner_app_id?: string;
        resource?: string;
        type?: string;
      };
      if (payload.type !== "maverick.widget.data-changed" || payload.owner_app_id !== "chat" || payload.resource !== "threads") {
        return;
      }
      const activeThreadId = typeof payload.active_thread_id === "string" ? payload.active_thread_id : "";
      const navigationScope = typeof payload.navigation_scope === "string" ? payload.navigation_scope : "";
      const pendingPreviousThreadId = navigationScope ? pendingNewChatPreviousThreadByWindow.current.get(navigationScope) : "";
      const currentWindows = windowsRef.current;
      debugThreadSync("widget.data-changed", {
        activeThreadId,
        navigationScope,
        pendingPreviousThreadId,
        windows: currentWindows.map((windowItem) => ({ id: windowItem.id, threadId: windowItem.threadId })),
      });
      if (pendingPreviousThreadId && !activeThreadId) {
        debugThreadSync("ignored-empty-pending-thread", { navigationScope, pendingPreviousThreadId });
        return;
      }
      if (pendingPreviousThreadId && activeThreadId === pendingPreviousThreadId) {
        debugThreadSync("ignored-previous-pending-thread", { activeThreadId, navigationScope });
        return;
      }
      if (pendingPreviousThreadId && activeThreadId && activeThreadId !== pendingPreviousThreadId) {
        pendingNewChatPreviousThreadByWindow.current.delete(navigationScope);
      }
      void refreshThreads(activeThreadId, navigationScope);
    }

    window.addEventListener("message", handleWidgetMessage);
    return () => {
      cancelled = true;
      window.removeEventListener("message", handleWidgetMessage);
    };
  }, []);

  async function refreshThreads(preferredThreadId = "", navigationScope = "") {
    const requestScope = navigationScope || "__global__";
    const requestId = (refreshThreadsRequestIdsByScopeRef.current.get(requestScope) || 0) + 1;
    refreshThreadsRequestIdsByScopeRef.current.set(requestScope, requestId);
    debugThreadSync("refresh-start", { navigationScope, preferredThreadId, requestId });
    try {
      const payload = await listThreads();
      const hydratedThreads = await withRuntimeAvailability(payload.threads || []);
      if (refreshThreadsRequestIdsByScopeRef.current.get(requestScope) !== requestId) {
        debugThreadSync("refresh-stale", {
          currentRequestId: refreshThreadsRequestIdsByScopeRef.current.get(requestScope),
          navigationScope,
          preferredThreadId,
          requestId,
        });
        return;
      }
      setThreads(hydratedThreads);
      setWindows((current) => {
        const nextWindows = reconcileWindowsWithThreads(current, hydratedThreads, preferredThreadId, navigationScope);
        if (areWindowThreadSelectionsEqual(current, nextWindows)) {
          debugThreadSync("refresh-apply-unchanged", {
            navigationScope,
            preferredThreadId,
            requestId,
            windows: current.map((windowItem) => ({ id: windowItem.id, threadId: windowItem.threadId })),
          });
          return current;
        }
        debugThreadSync("refresh-apply", {
          navigationScope,
          preferredThreadId,
          requestId,
          previous: current.map((windowItem) => ({ id: windowItem.id, threadId: windowItem.threadId })),
          next: nextWindows.map((windowItem) => ({ id: windowItem.id, threadId: windowItem.threadId })),
        });
        return nextWindows;
      });
    } catch {
      debugThreadSync("refresh-error", { navigationScope, preferredThreadId, requestId });
      setThreads([]);
    }
  }

  function navigateChat(windowId: string, params: Record<string, string | boolean | null>) {
    window.postMessage({ type: "maverick.app.navigate", app_id: "chat", navigation_scope: windowId, params }, window.location.origin);
  }

  function notifyChatDataChanged(resource: string, detail: Record<string, string> = {}) {
    window.parent?.postMessage(
      {
        type: "maverick.app.data-changed",
        owner_app_id: "chat",
        resource,
        ...detail,
      },
      window.location.origin,
    );
  }

  function setWindowThread(windowId: string, threadId: string) {
    debugThreadSync("set-window-thread", { threadId, windowId });
    setWindows((current) => current.map((windowItem) => (windowItem.id === windowId && windowItem.threadId !== threadId ? { ...windowItem, threadId } : windowItem)));
  }

  function setWindowCollapsed(windowId: string, isCollapsed: boolean) {
    setWindows((current) => current.map((windowItem) => (windowItem.id === windowId ? { ...windowItem, isCollapsed } : windowItem)));
  }

  function setWindowExecutionMode(windowId: string, executionMode: string) {
    setWindows((current) => current.map((windowItem) => (windowItem.id === windowId ? { ...windowItem, executionMode } : windowItem)));
  }

  function selectThread(windowId: string, threadId: string) {
    debugThreadSync("select-thread", { threadId, windowId });
    setWindowThread(windowId, threadId);
    if (threadId) {
      navigateChat(windowId, { thread_id: threadId });
    }
  }

  function createChat(windowId: string) {
    const currentThreadId = windows.find((windowItem) => windowItem.id === windowId)?.threadId || "";
    debugThreadSync("create-chat", { previousThreadId: currentThreadId, windowId });
    pendingNewChatPreviousThreadByWindow.current.set(windowId, currentThreadId);
    setWindowThread(windowId, "");
    navigateChat(windowId, { new_chat: true, new_chat_request_id: crypto.randomUUID() });
  }

  function splitWindow(sourceWindowId: string) {
    setWindows((current) => {
      const sourceIndex = current.findIndex((windowItem) => windowItem.id === sourceWindowId);
      const sourceWindow = sourceIndex >= 0 ? current[sourceIndex] : current[current.length - 1];
      const nextThreadId = threads.find((thread) => !current.some((windowItem) => windowItem.threadId === thread.thread_id))?.thread_id || sourceWindow?.threadId || "";
      const nextWindow = createWindow(nextThreadId);
      const insertionIndex = sourceIndex >= 0 ? sourceIndex + 1 : current.length;
      return [...current.slice(0, insertionIndex), nextWindow, ...current.slice(insertionIndex)];
    });
  }

  async function renameThread(threadId: string, title: string) {
    const payload = await updateThread({ thread_id: threadId, title });
    const hydratedThreads = await withRuntimeAvailability(payload.threads || []);
    setThreads(hydratedThreads);
    notifyChatDataChanged("threads", { active_thread_id: payload.thread.thread_id });
  }

  async function removeThread(windowId: string, thread: ChatThread) {
    const payload = await deleteThread(thread.thread_id);
    const hydratedThreads = await withRuntimeAvailability(payload.threads || []);
    const nextThreadId = hydratedThreads[0]?.thread_id || "";
    setThreads(hydratedThreads);
    setWindows((current) => current.map((windowItem) => (windowItem.threadId === thread.thread_id ? { ...windowItem, threadId: nextThreadId } : windowItem)));
    notifyChatDataChanged("threads", { deleted_thread_id: thread.thread_id, ...(nextThreadId ? { active_thread_id: nextThreadId, navigation_scope: windowId } : {}) });
    if (nextThreadId) {
      navigateChat(windowId, { thread_id: nextThreadId });
    }
  }

  return (
    <div className="chat-floating-widget-stack">
      {windows.map((windowItem) => (
        <ChatFloatingWindow
          key={windowItem.id}
          onCollapseChange={setWindowCollapsed}
          onCreateChat={createChat}
          onExecutionModeChange={setWindowExecutionMode}
          onRemoveThread={removeThread}
          onRenameThread={renameThread}
          onSelectThread={selectThread}
          onSplit={splitWindow}
          threads={threads}
          windowItem={windowItem}
        />
      ))}
    </div>
  );
}

function ChatFloatingWindow({
  onCollapseChange,
  onCreateChat,
  onExecutionModeChange,
  onRemoveThread,
  onRenameThread,
  onSelectThread,
  onSplit,
  threads,
  windowItem,
}: {
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateChat: (windowId: string) => void;
  onExecutionModeChange: (windowId: string, executionMode: string) => void;
  onRemoveThread: (windowId: string, thread: ChatThread) => void;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
  onSplit: (windowId: string) => void;
  threads: ChatThread[];
  windowItem: ChatWindow;
}) {
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingThreadTitle, setEditingThreadTitle] = useState("");
  const [isThreadMenuOpen, setIsThreadMenuOpen] = useState(false);
  const threadMenuRef = useRef<HTMLDivElement | null>(null);
  const activeThread = threads.find((thread) => thread.thread_id === windowItem.threadId) || null;

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
        setEditingThreadId(null);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isThreadMenuOpen]);

  useEffect(() => {
    void refreshExecutionMode(activeThread);
  }, [activeThread?.runtime_session_id, windowItem.id]);

  async function refreshExecutionMode(thread: ChatThread | null) {
    if (!thread?.runtime_session_id) {
      onExecutionModeChange(windowItem.id, "runtime");
      return;
    }
    try {
      const session = await getRuntimeSession(thread.runtime_session_id);
      onExecutionModeChange(windowItem.id, session.effective_mode || "runtime");
    } catch {
      onExecutionModeChange(windowItem.id, "runtime");
    }
  }

  function selectThread(threadId: string) {
    if (editingThreadId) {
      return;
    }
    setIsThreadMenuOpen(false);
    onSelectThread(windowItem.id, threadId);
  }

  function startRenameThread(thread: ChatThread) {
    setEditingThreadId(thread.thread_id);
    setEditingThreadTitle(thread.title || "New chat");
  }

  async function saveRenameThread() {
    if (!editingThreadId) {
      return;
    }
    const title = editingThreadTitle.trim();
    if (title) {
      await onRenameThread(editingThreadId, title);
    }
    setEditingThreadId(null);
    setEditingThreadTitle("");
  }

  if (windowItem.isCollapsed) {
    return (
      <button aria-label="Apri chat" className="chat-floating-widget-launcher" onClick={() => onCollapseChange(windowItem.id, false)} type="button">
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
                  const isEditing = editingThreadId === thread.thread_id;
                  return (
                    <div
                      className={`chat-floating-thread-menu__item ${windowItem.threadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""}`}
                      key={thread.thread_id}
                      role="menuitem"
                    >
                      {isEditing ? (
                        <input
                          aria-label="Rinomina chat"
                          autoFocus
                          className="chat-floating-thread-menu__rename-input"
                          onChange={(event) => setEditingThreadTitle(event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              void saveRenameThread();
                            }
                            if (event.key === "Escape") {
                              setEditingThreadId(null);
                              setEditingThreadTitle("");
                            }
                          }}
                          value={editingThreadTitle}
                        />
                      ) : (
                        <button className="chat-floating-thread-menu__item-select" onClick={() => selectThread(thread.thread_id)} type="button">
                          <span className="chat-floating-thread-menu__item-copy">
                            <span className="chat-floating-thread-menu__item-title">{thread.title || "New chat"}</span>
                          </span>
                          {isBusy ? <span aria-label="Chat in lavoro" className="chat-floating-thread-menu__presence is-busy" title="Chat in lavoro" /> : null}
                        </button>
                      )}
                      <div className="chat-floating-thread-menu__item-actions">
                        <button
                          aria-label={`Rinomina ${thread.title || "chat"}`}
                          className="chat-floating-thread-menu__icon-action"
                          onClick={(event) => {
                            event.stopPropagation();
                            startRenameThread(thread);
                          }}
                          type="button"
                        >
                          <span aria-hidden="true" className="material-symbols-rounded">
                            edit
                          </span>
                        </button>
                        <button
                          aria-label={`Cancella ${thread.title || "chat"}`}
                          className="chat-floating-thread-menu__icon-action is-danger"
                          onClick={(event) => {
                            event.stopPropagation();
                            void onRemoveThread(windowItem.id, thread);
                          }}
                          type="button"
                        >
                          <span aria-hidden="true" className="material-symbols-rounded">
                            delete
                          </span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
          <button aria-label="Nuova chat" className="chat-floating-widget-shell__button" onClick={() => onCreateChat(windowItem.id)} type="button">
            <span aria-hidden="true" className="material-symbols-rounded">
              add
            </span>
          </button>
        </div>
        <div className="chat-floating-widget-shell__runtime-tools">
          <button aria-label="Sdoppia chat" className="chat-floating-widget-shell__button" onClick={() => onSplit(windowItem.id)} title="Sdoppia chat" type="button">
            <span aria-hidden="true" className="material-symbols-rounded">
              add_box
            </span>
          </button>
          <span
            aria-label={windowItem.executionMode}
            className={`chat-floating-widget-shell__mode-icon ${windowItem.executionMode === "full-access" ? "is-full-access" : "is-sandbox"}`}
            role="img"
            title={windowItem.executionMode}
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              {windowItem.executionMode === "full-access" ? "admin_panel_settings" : "lock"}
            </span>
          </span>
        </div>
        <button aria-label="Collassa chat" className="chat-floating-widget-shell__button" onClick={() => onCollapseChange(windowItem.id, true)} type="button">
          <span aria-hidden="true" className="material-symbols-rounded">
            keyboard_arrow_down
          </span>
        </button>
      </header>
      <div className="chat-floating-widget-shell__body">
        <App enablePageCapture navigationScope={windowItem.id} threadId={windowItem.threadId} />
      </div>
    </section>
  );
}

function reconcileWindowsWithThreads(windows: ChatWindow[], threads: ChatThread[], preferredThreadId = "", navigationScope = "") {
  const firstThreadId = threads[0]?.thread_id || "";
  return windows.map((windowItem) => {
    if (!navigationScope) {
      return windowItem.threadId && threads.some((thread) => thread.thread_id === windowItem.threadId) ? windowItem : { ...windowItem, threadId: firstThreadId };
    }
    if (navigationScope && windowItem.id !== navigationScope) {
      return threads.some((thread) => thread.thread_id === windowItem.threadId) ? windowItem : { ...windowItem, threadId: firstThreadId };
    }
    const nextThreadId =
      preferredThreadId && threads.some((thread) => thread.thread_id === preferredThreadId)
        ? preferredThreadId
        : windowItem.threadId && threads.some((thread) => thread.thread_id === windowItem.threadId)
          ? windowItem.threadId
          : firstThreadId;
    return { ...windowItem, threadId: nextThreadId };
  });
}

function areWindowThreadSelectionsEqual(previousWindows: ChatWindow[], nextWindows: ChatWindow[]) {
  if (previousWindows.length !== nextWindows.length) {
    return false;
  }
  return previousWindows.every((windowItem, index) => {
    const nextWindow = nextWindows[index];
    return Boolean(nextWindow) && windowItem.id === nextWindow.id && windowItem.threadId === nextWindow.threadId;
  });
}

postWidgetSize(readPersistedWindows());

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ChatFloatingMount />
  </React.StrictMode>,
);
