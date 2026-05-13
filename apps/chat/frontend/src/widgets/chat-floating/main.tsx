import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "../../App";
import type { ChatThread } from "../../api/client";
import { deleteThread, getWidgetContext, updateThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { isThreadBusy } from "../chat-sidebar/sections";
import {
  floatingWidgetSize,
  horizontalDragScrollLeft,
  isHorizontalDragIntent,
  isVerticalDragIntent,
} from "./floatingLayout";
import "../../styles/main.css";
import "./styles.css";

const WIDGET_STATE_STORAGE_KEY_PREFIX = "maverick.chat.floating-widget.state.v1";
const FALLBACK_WIDGET_STATE_STORAGE_KEY = `${WIDGET_STATE_STORAGE_KEY_PREFIX}:global`;
const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";

type ChatWindow = {
  draftProjectId: string | null;
  id: string;
  isDraft: boolean;
  isCollapsed: boolean;
  threadId: string;
};

type PersistedChatWindow = {
  draftProjectId?: string | null;
  id: string;
  isDraft?: boolean;
  isCollapsed: boolean;
  threadId: string;
};

type PersistedWidgetState = {
  version: 1;
  windows: PersistedChatWindow[];
};

type FloatingStackDragState = {
  isDragging: boolean;
  pointerId: number;
  scrollLeft: number;
  startX: number;
  startY: number;
};

function createWindow(threadId = "", isDraft = false, draftProjectId: string | null = null): ChatWindow {
  return {
    draftProjectId,
    id: `window-${crypto.randomUUID()}`,
    isDraft,
    isCollapsed: false,
    threadId,
  };
}

function windowFromPersistedState(windowItem: PersistedChatWindow): ChatWindow {
  return {
    draftProjectId: typeof windowItem.draftProjectId === "string" ? windowItem.draftProjectId : null,
    id: windowItem.id,
    isDraft: windowItem.isDraft === true,
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
          draftProjectId: typeof windowItem.draftProjectId === "string" ? windowItem.draftProjectId : null,
          id,
          isDraft: windowItem.isDraft === true,
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
        draftProjectId: windowItem.draftProjectId,
        id: windowItem.id,
        isDraft: windowItem.isDraft,
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
  const token = widgetContextToken();
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

function widgetContextToken(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("context") || new URLSearchParams(window.location.search).get("context") || "";
}

function postWidgetSize(windows: ChatWindow[]) {
  window.parent?.postMessage(
    {
      ...floatingWidgetSize(windows),
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

const FLOATING_STACK_DRAG_IGNORE_SELECTOR =
  'button, a, input, textarea, select, summary, [contenteditable="true"], [role="button"], [role="textbox"], [role="menuitem"]';

function shouldIgnoreFloatingStackDrag(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(FLOATING_STACK_DRAG_IGNORE_SELECTOR));
}

function ChatFloatingMount() {
  const [storageKey, setStorageKey] = useState(FALLBACK_WIDGET_STATE_STORAGE_KEY);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [, setRuntimeThreadError] = useState<string | null>(null);
  const [windows, setWindows] = useState<ChatWindow[]>(readPersistedWindows);
  const stackDragRef = useRef<FloatingStackDragState | null>(null);
  const stackRef = useRef<HTMLDivElement | null>(null);
  const threadsRef = useRef(threads);
  const windowsRef = useRef(windows);

  useRuntimeThreads({ setError: setRuntimeThreadError, setThreads });

  useEffect(() => {
    threadsRef.current = threads;
    setWindows((current) => reconcileWindowsWithThreads(current, threads));
  }, [threads]);

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

    function handleWidgetMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        navigation_scope?: string;
        owner_app_id?: string;
        type?: string;
      };
      if (payload.type !== "maverick.chat.active-thread-changed" || payload.owner_app_id !== "chat") {
        return;
      }
      const activeThreadId = typeof payload.active_thread_id === "string" ? payload.active_thread_id : "";
      const navigationScope = typeof payload.navigation_scope === "string" ? payload.navigation_scope : "";
      const currentWindows = windowsRef.current;
      debugThreadSync("widget.data-changed", {
        activeThreadId,
        navigationScope,
        windows: currentWindows.map((windowItem) => ({ id: windowItem.id, threadId: windowItem.threadId })),
      });
      setWindows((current) => reconcileWindowsWithThreads(current, threadsRef.current, activeThreadId, navigationScope));
    }

    window.addEventListener("message", handleWidgetMessage);
    return () => {
      cancelled = true;
      window.removeEventListener("message", handleWidgetMessage);
    };
  }, []);

  function navigateChat(windowId: string, params: Record<string, string | boolean | null>) {
    window.postMessage({ type: "maverick.app.navigate", app_id: "chat", navigation_scope: windowId, params }, window.location.origin);
  }

  function setWindowThread(windowId: string, threadId: string) {
    debugThreadSync("set-window-thread", { threadId, windowId });
    setWindows((current) =>
      current.map((windowItem) =>
        windowItem.id === windowId && (windowItem.threadId !== threadId || windowItem.isDraft)
          ? { ...windowItem, draftProjectId: null, isDraft: false, threadId }
          : windowItem,
      ),
    );
  }

  function setWindowCollapsed(windowId: string, isCollapsed: boolean) {
    setWindows((current) => current.map((windowItem) => (windowItem.id === windowId ? { ...windowItem, isCollapsed } : windowItem)));
  }

  function closeWindow(windowId: string) {
    setWindows((current) => {
      if (current.length <= 1) {
        return current.map((windowItem) => (windowItem.id === windowId ? { ...windowItem, isCollapsed: true } : windowItem));
      }
      return current.filter((windowItem) => windowItem.id !== windowId);
    });
  }

  function createDraftChat(windowId: string, projectId: string | null = null) {
    debugThreadSync("create-draft-chat", { projectId, windowId });
    const nextWindow = createWindow("", true, projectId);
    setWindows((current) => [...current, nextWindow]);
  }

  function selectThread(windowId: string, threadId: string) {
    debugThreadSync("select-thread", { threadId, windowId });
    if (!threadId) {
      return;
    }
    const currentWindows = windowsRef.current;
    const sourceWindow = currentWindows.find((windowItem) => windowItem.id === windowId);
    if (sourceWindow?.threadId === threadId && !sourceWindow.isDraft) {
      return;
    }
    const existingWindow = currentWindows.find((windowItem) => windowItem.threadId === threadId && !windowItem.isDraft);
    if (existingWindow) {
      setWindows((current) =>
        current.map((windowItem) => (windowItem.id === existingWindow.id ? { ...windowItem, isCollapsed: false } : windowItem)),
      );
      return;
    }
    setWindows((current) => [...current, createWindow(threadId)]);
  }

  async function renameThread(threadId: string, title: string) {
    await updateThread({ thread_id: threadId, title });
  }

  async function removeThread(windowId: string, thread: ChatThread) {
    const nextThreads = threads.filter((item) => item.thread_id !== thread.thread_id);
    const nextThreadId = nextThreads[0]?.thread_id || "";
    setWindows((current) => current.map((windowItem) => (windowItem.threadId === thread.thread_id ? { ...windowItem, threadId: nextThreadId } : windowItem)));
    await deleteThread(thread.thread_id);
    if (nextThreadId) {
      navigateChat(windowId, { thread_id: nextThreadId });
    }
  }

  function startStackDrag(event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "mouse" || event.button !== 0 || shouldIgnoreFloatingStackDrag(event.target)) {
      return;
    }
    const stack = stackRef.current;
    if (!stack || stack.scrollWidth <= stack.clientWidth) {
      return;
    }
    stackDragRef.current = {
      isDragging: false,
      pointerId: event.pointerId,
      scrollLeft: stack.scrollLeft,
      startX: event.clientX,
      startY: event.clientY,
    };
  }

  function moveStackDrag(event: React.PointerEvent<HTMLDivElement>) {
    const dragState = stackDragRef.current;
    const stack = stackRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId || !stack) {
      return;
    }

    const deltaX = event.clientX - dragState.startX;
    const deltaY = event.clientY - dragState.startY;
    if (!dragState.isDragging) {
      if (isVerticalDragIntent(deltaX, deltaY)) {
        stackDragRef.current = null;
        return;
      }
      if (!isHorizontalDragIntent(deltaX, deltaY)) {
        return;
      }
      dragState.isDragging = true;
      stack.setPointerCapture(event.pointerId);
      stack.classList.add("is-horizontal-dragging");
    }

    event.preventDefault();
    stack.scrollLeft = horizontalDragScrollLeft(dragState.scrollLeft, dragState.startX, event.clientX);
  }

  function endStackDrag(event: React.PointerEvent<HTMLDivElement>) {
    const dragState = stackDragRef.current;
    const stack = stackRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId || !stack) {
      return;
    }
    if (stack.hasPointerCapture(event.pointerId)) {
      stack.releasePointerCapture(event.pointerId);
    }
    stack.classList.remove("is-horizontal-dragging");
    stackDragRef.current = null;
  }

  const hasMultipleWindows = windows.length > 1;

  return (
    <div
      className={`chat-floating-widget-stack ${hasMultipleWindows ? "has-multiple-windows" : "has-single-window"}`}
      onLostPointerCapture={endStackDrag}
      onPointerCancel={endStackDrag}
      onPointerDown={startStackDrag}
      onPointerMove={moveStackDrag}
      onPointerUp={endStackDrag}
      ref={stackRef}
    >
      {windows.map((windowItem) => (
        <ChatFloatingWindow
          key={windowItem.id}
          onClose={closeWindow}
          onCollapseChange={setWindowCollapsed}
          onCreateDraftChat={createDraftChat}
          onRemoveThread={removeThread}
          onRenameThread={renameThread}
          onSelectThread={selectThread}
          threads={threads}
          windowItem={windowItem}
        />
      ))}
    </div>
  );
}

function ChatFloatingWindow({
  onClose,
  onCollapseChange,
  onCreateDraftChat,
  onRemoveThread,
  onRenameThread,
  onSelectThread,
  threads,
  windowItem,
}: {
  onClose: (windowId: string) => void;
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onRemoveThread: (windowId: string, thread: ChatThread) => void;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
  threads: ChatThread[];
  windowItem: ChatWindow;
}) {
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingThreadTitle, setEditingThreadTitle] = useState("");
  const [isThreadMenuOpen, setIsThreadMenuOpen] = useState(false);
  const threadMenuRef = useRef<HTMLDivElement | null>(null);
  const activeThread = threads.find((thread) => thread.thread_id === windowItem.threadId) || null;
  const isActiveThreadBusy = Boolean(activeThread && isThreadBusy(activeThread));

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

  return (
    <>
      <button
        aria-busy={isActiveThreadBusy || undefined}
        aria-label={isActiveThreadBusy ? "Apri chat in corso" : "Apri chat"}
        className={`chat-floating-widget-launcher ${windowItem.isCollapsed ? "" : "is-hidden"} ${isActiveThreadBusy ? "is-busy" : ""}`}
        onClick={() => onCollapseChange(windowItem.id, false)}
        type="button"
      >
        {isActiveThreadBusy ? <BusyChatGlow /> : null}
        <span aria-hidden="true" className="material-symbols-rounded">
          forum
        </span>
      </button>
      <section className={`chat-floating-widget-shell ${windowItem.isCollapsed ? "is-hidden" : ""}`} aria-label="Chat">
        <header className="chat-floating-widget-shell__bar">
          <div className="chat-floating-widget-shell__thread-tools">
            <div className="chat-floating-thread-menu" ref={threadMenuRef}>
              <button
                aria-expanded={isThreadMenuOpen}
                aria-haspopup="menu"
                aria-label="Scegli chat"
                className={`chat-floating-thread-menu__trigger ${isActiveThreadBusy ? "is-busy" : ""}`}
                disabled={threads.length === 0}
                onClick={() => setIsThreadMenuOpen((current) => !current)}
                type="button"
              >
                {isActiveThreadBusy ? <BusyChatGlow /> : null}
                <span className="chat-floating-thread-menu__trigger-title">{activeThread?.title || "New chat"}</span>
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
                        {isBusy ? <BusyChatGlow /> : null}
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
          </div>
          <div className="chat-floating-widget-shell__actions">
            <button
              aria-label="Nuova chat"
              className="chat-floating-widget-shell__button"
              onClick={() => onCreateDraftChat(windowItem.id, activeThread?.project_id || null)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                add
              </span>
            </button>
            <button aria-label="Collassa chat" className="chat-floating-widget-shell__button" onClick={() => onCollapseChange(windowItem.id, true)} type="button">
              <span aria-hidden="true" className="material-symbols-rounded">
                keyboard_arrow_down
              </span>
            </button>
            <button
              aria-label="Chiudi chat"
              className="chat-floating-widget-shell__button chat-floating-widget-shell__button--danger chat-floating-widget-shell__button--close"
              onClick={() => onClose(windowItem.id)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                close
              </span>
            </button>
          </div>
        </header>
        <div className="chat-floating-widget-shell__body">
          <App
            enablePageCapture
            navigationScope={windowItem.id}
            newChatProjectId={windowItem.draftProjectId}
            newChatRequestId={windowItem.isDraft ? windowItem.id : null}
            threadId={windowItem.threadId}
          />
        </div>
      </section>
    </>
  );
}

function BusyChatGlow() {
  return (
    <span aria-hidden="true" className="bs-chat-list__glow">
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--outer" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--a" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--b" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--c" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--bright" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--rim" />
    </span>
  );
}

function reconcileWindowsWithThreads(windows: ChatWindow[], threads: ChatThread[], preferredThreadId = "", navigationScope = "") {
  const firstThreadId = threads[0]?.thread_id || "";
  return windows.map((windowItem) => {
    if (windowItem.isDraft && (!navigationScope || windowItem.id !== navigationScope)) {
      return windowItem;
    }
    if (windowItem.isDraft && navigationScope === windowItem.id && !preferredThreadId) {
      return windowItem;
    }
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
    return { ...windowItem, draftProjectId: null, isDraft: false, threadId: nextThreadId };
  });
}

postWidgetSize(readPersistedWindows());

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ChatFloatingMount />
  </React.StrictMode>,
);
