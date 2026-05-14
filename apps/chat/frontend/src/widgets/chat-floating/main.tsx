import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "../../App";
import type { ExternalFileDrop, ExternalMentionDrop } from "../../App";
import type { ChatThread } from "../../api/client";
import { deleteThread, getWidgetContext, markThreadRead, updateThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { filesFromDataTransfer, hasFileDropData } from "../../lib/fileDropAttachments";
import { hasStorageReferenceDragData, storageReferenceMentionItemsFromDataTransfer } from "../../lib/storageDragReferences";
import { isThreadBusy, isThreadUnread } from "../chat-sidebar/sections";
import {
  floatingWidgetSize,
  horizontalDragScrollLeft,
  isHorizontalDragIntent,
  isVerticalDragIntent,
} from "./floatingLayout";
import {
  FALLBACK_WIDGET_STATE_STORAGE_KEY,
  type FloatingChatWindow,
  createWindow,
  persistWindows,
  readPersistedOrDefaultWindows,
  reconcileWindowsWithThreads,
  widgetStateStorageKey,
} from "./floatingState";
import "../../styles/main.css";
import "./styles.css";

const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";

type FloatingStackDragState = {
  isDragging: boolean;
  pointerId: number;
  scrollLeft: number;
  startX: number;
  startY: number;
};

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

function postWidgetSize(windows: FloatingChatWindow[]) {
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
  const [storageKey, setStorageKey] = useState<string | null>(null);
  const [isWindowStateReady, setIsWindowStateReady] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [, setRuntimeThreadError] = useState<string | null>(null);
  const [windows, setWindows] = useState<FloatingChatWindow[]>([]);
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const stackDragRef = useRef<FloatingStackDragState | null>(null);
  const stackRef = useRef<HTMLDivElement | null>(null);
  const threadsRef = useRef(threads);
  const windowsRef = useRef(windows);

  useRuntimeThreads({ setError: setRuntimeThreadError, setThreads });

  useEffect(() => {
    threadsRef.current = threads;
    if (!isWindowStateReady) {
      return;
    }
    setWindows((current) => reconcileWindowsWithThreads(current, threads));
  }, [isWindowStateReady, threads]);

  useEffect(() => {
    windowsRef.current = windows;
    if (!isWindowStateReady || !storageKey) {
      return;
    }
    postWidgetSize(windows);
    persistWindows(storageKey, windows);
  }, [isWindowStateReady, storageKey, windows]);

  useEffect(() => {
    let cancelled = false;
    async function loadScopedWidgetState() {
      const nextStorageKey = await loadWidgetStateStorageKey();
      if (cancelled) {
        return;
      }
      const persistedWindows = readPersistedOrDefaultWindows(nextStorageKey);
      setStorageKey(nextStorageKey);
      setWindows(persistedWindows);
      setIsWindowStateReady(true);
      postWidgetSize(persistedWindows);
    }

    void loadScopedWidgetState();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
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
      if (!isWindowStateReady) {
        return;
      }
      setWindows((current) => reconcileWindowsWithThreads(current, threadsRef.current, activeThreadId, navigationScope));
    }

    window.addEventListener("message", handleWidgetMessage);
    return () => {
      window.removeEventListener("message", handleWidgetMessage);
    };
  }, [isWindowStateReady]);

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

  async function markThreadReadIfNeeded(thread: ChatThread) {
    if (!isThreadUnread(thread) || readReceiptInFlightRef.current.has(thread.thread_id)) {
      return;
    }
    readReceiptInFlightRef.current.add(thread.thread_id);
    setThreads((current) =>
      current.map((item) => (item.thread_id === thread.thread_id ? { ...item, has_unread_completed_response: false } : item)),
    );
    try {
      const payload = await markThreadRead(thread.thread_id);
      setThreads(payload.threads);
    } catch {
      // Opening a floating chat should not be blocked by a best-effort read receipt.
    } finally {
      readReceiptInFlightRef.current.delete(thread.thread_id);
    }
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

  if (!isWindowStateReady) {
    return null;
  }

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
          onMarkThreadRead={markThreadReadIfNeeded}
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
  onMarkThreadRead,
  onRemoveThread,
  onRenameThread,
  onSelectThread,
  threads,
  windowItem,
}: {
  onClose: (windowId: string) => void;
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onRemoveThread: (windowId: string, thread: ChatThread) => void;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
}) {
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingThreadTitle, setEditingThreadTitle] = useState("");
  const [externalFileDrop, setExternalFileDrop] = useState<ExternalFileDrop | null>(null);
  const [externalMentionDrop, setExternalMentionDrop] = useState<ExternalMentionDrop | null>(null);
  const [isThreadMenuOpen, setIsThreadMenuOpen] = useState(false);
  const threadMenuRef = useRef<HTMLDivElement | null>(null);
  const activeThread = threads.find((thread) => thread.thread_id === windowItem.threadId) || null;
  const isActiveThreadBusy = Boolean(activeThread && isThreadBusy(activeThread));
  const isActiveThreadUnread = Boolean(activeThread && isThreadUnread(activeThread));

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
    const thread = threads.find((item) => item.thread_id === threadId);
    if (thread) {
      void onMarkThreadRead(thread);
    }
    onSelectThread(windowItem.id, threadId);
  }

  function openCollapsedThread() {
    onCollapseChange(windowItem.id, false);
    if (activeThread) {
      void onMarkThreadRead(activeThread);
    }
  }

  function handleFloatingDragOver(event: React.DragEvent<HTMLElement>) {
    if (!hasStorageReferenceDragData(event.dataTransfer) && !hasFileDropData(event.dataTransfer)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleFloatingDrop(event: React.DragEvent<HTMLElement>) {
    if (!hasStorageReferenceDragData(event.dataTransfer)) {
      const files = filesFromDataTransfer(event.dataTransfer);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      onCollapseChange(windowItem.id, false);
      setExternalFileDrop({
        files,
        requestId: crypto.randomUUID(),
      });
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const items = storageReferenceMentionItemsFromDataTransfer(event.dataTransfer);
    if (!items.length) {
      return;
    }
    onCollapseChange(windowItem.id, false);
    setExternalMentionDrop({
      items,
      requestId: crypto.randomUUID(),
    });
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
        aria-label={isActiveThreadBusy ? "Open active chat" : isActiveThreadUnread ? "Open chat with unread response" : "Open chat"}
        className={`chat-floating-widget-launcher ${windowItem.isCollapsed ? "" : "is-hidden"} ${isActiveThreadBusy ? "is-busy" : ""} ${isActiveThreadUnread ? "is-unread" : ""}`}
        onClick={openCollapsedThread}
        onDragOver={handleFloatingDragOver}
        onDrop={handleFloatingDrop}
        type="button"
      >
        {isActiveThreadBusy ? <BusyChatGlow /> : null}
        <span aria-hidden="true" className="material-symbols-rounded">
          forum
        </span>
      </button>
      <section
        className={`chat-floating-widget-shell ${windowItem.isCollapsed ? "is-hidden" : ""}`}
        aria-label="Chat"
        onDragOver={handleFloatingDragOver}
        onDrop={handleFloatingDrop}
      >
        <header className="chat-floating-widget-shell__bar">
          <div className="chat-floating-widget-shell__thread-tools">
            <div className="chat-floating-thread-menu" ref={threadMenuRef}>
              <button
                aria-expanded={isThreadMenuOpen}
                aria-haspopup="menu"
                aria-label="Choose chat"
                className={`chat-floating-thread-menu__trigger ${isActiveThreadBusy ? "is-busy" : ""} ${isActiveThreadUnread ? "is-unread" : ""}`}
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
                    const isUnread = isThreadUnread(thread);
                    const isEditing = editingThreadId === thread.thread_id;
                    return (
                      <div
                        className={`chat-floating-thread-menu__item ${windowItem.threadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""} ${isUnread ? "is-unread" : ""}`}
                        key={thread.thread_id}
                        role="menuitem"
                      >
                        {isBusy ? <BusyChatGlow /> : null}
                        {isEditing ? (
                          <input
                            aria-label="Rename chat"
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
                            aria-label={`Rename ${thread.title || "chat"}`}
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
                            aria-label={`Delete ${thread.title || "chat"}`}
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
              aria-label="New chat"
              className="chat-floating-widget-shell__button"
              onClick={() => onCreateDraftChat(windowItem.id, activeThread?.project_id || null)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                add
              </span>
            </button>
            <button aria-label="Collapse chat" className="chat-floating-widget-shell__button" onClick={() => onCollapseChange(windowItem.id, true)} type="button">
              <span aria-hidden="true" className="material-symbols-rounded">
                keyboard_arrow_down
              </span>
            </button>
            <button
              aria-label="Close chat"
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
            externalFileDrop={externalFileDrop}
            externalMentionDrop={externalMentionDrop}
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

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ChatFloatingMount />
  </React.StrictMode>,
);
