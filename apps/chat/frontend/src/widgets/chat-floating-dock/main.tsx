import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "../../styles/main.css";
import "../chat-floating/styles.css";
import { applyThreadCatalogPayload, deleteThread, markThreadRead, updateThread } from "../../api/client";
import type { ChatThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { applyInitialMaverickTheme, listenForMaverickThemeMessages } from "../../lib/shellTheme";
import { isThreadUnread } from "../chat-sidebar/sections";
import {
  DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE,
  floatingDockContextFromContent,
  floatingDockWindowAfterWidgetMessage,
  floatingDockWindowFromContext,
} from "../chat-floating/floatingDockState";
import { FloatingChatFrame } from "../chat-floating/FloatingChatFrame";
import { createWindow, persistWindows, readPersistedWindows, reconcileWindowsWithThreads, widgetStateStorageKey } from "../chat-floating/floatingState";
import type { FloatingChatWindow } from "../chat-floating/floatingState";
import { debugThreadSync, loadFloatingDockContext, postDockClose } from "../chat-floating/floatingWidgetRuntime";

applyInitialMaverickTheme();
listenForMaverickThemeMessages();

function ChatFloatingDockMount() {
  const dock = useFloatingDockWindow();

  if (!dock.isReady) {
    return null;
  }

  return (
    <div className="chat-floating-dock-root">
      <FloatingChatFrame
        className={dock.mode === "mobile-fullscreen" ? "chat-floating-widget-shell--mobile-fullscreen" : "chat-floating-widget-shell--dock"}
        onClose={dock.closeDock}
        onCollapseChange={dock.setWindowCollapsed}
        onCreateDraftChat={dock.createDraftChat}
        onMarkThreadRead={dock.markThreadReadIfNeeded}
        onOverlay={dock.closeDock}
        onRemoveThread={dock.removeThread}
        onRenameThread={dock.renameThread}
        onSelectThread={dock.selectThread}
        runtimeThreadsError={dock.runtimeThreadsError}
        runtimeThreadsLoaded={dock.runtimeThreadsLoaded}
        showCollapse={false}
        showClose={dock.mode !== "mobile-fullscreen"}
        showOverlay={dock.mode !== "mobile-fullscreen"}
        threads={dock.threads}
        windowItem={dock.windowItem}
      />
    </div>
  );
}

function useFloatingDockWindow() {
  const [isReady, setIsReady] = useState(false);
  const [runtimeThreadsLoaded, setRuntimeThreadsLoaded] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [runtimeThreadsError, setRuntimeThreadsError] = useState<string | null>(null);
  const [mode, setMode] = useState<"fixed-right" | "mobile-fullscreen">("fixed-right");
  const [storageKey, setStorageKey] = useState<string | null>(null);
  const [windowItem, setWindowItem] = useState<FloatingChatWindow>(() => ({
    ...createWindow(),
    id: DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE,
  }));
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const threadsRef = useRef(threads);
  const windowItemRef = useRef(windowItem);

  useRuntimeThreads({ onSnapshot: () => setRuntimeThreadsLoaded(true), setError: setRuntimeThreadsError, setThreads });

  useEffect(() => {
    threadsRef.current = threads;
    updateDockWindowItem((current) => reconcileWindowsWithThreads([current], threads, current.threadId, current.id)[0] || current);
  }, [threads]);

  useEffect(() => {
    windowItemRef.current = windowItem;
  }, [windowItem]);

  useEffect(() => {
    if (!isReady || !storageKey) {
      return;
    }
    persistWindows(storageKey, [windowItem]);
  }, [isReady, storageKey, windowItem]);

  useEffect(() => {
    let cancelled = false;
    async function loadContext() {
      const context = await loadFloatingDockContext();
      if (cancelled) {
        return;
      }
      const nextStorageKey = context.workspaceId ? widgetStateStorageKey(context.workspaceId) : null;
      const persistedWindows = nextStorageKey ? readPersistedWindows(nextStorageKey) || [] : [];
      setMode(context.mode);
      setStorageKey(nextStorageKey);
      setDockWindowItem(floatingDockWindowFromContext(context, persistedWindows));
      setIsReady(true);
    }

    void loadContext();
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
        context?: { content?: unknown };
        owner_app_id?: string;
        type?: string;
        widget_id?: string;
      };
      if (payload.type === "maverick.widget.context-changed" && payload.owner_app_id === "chat") {
        setMode(floatingDockContextFromContent(payload.context?.content).mode);
      }
      updateDockWindowItem((current) => floatingDockWindowAfterWidgetMessage(current, payload));
    }

    window.addEventListener("message", handleWidgetMessage);
    return () => window.removeEventListener("message", handleWidgetMessage);
  }, []);

  function navigateChat(windowId: string, params: Record<string, string | boolean | null>) {
    window.postMessage({ type: "maverick.app.navigate", app_id: "chat", navigation_scope: windowId, params }, window.location.origin);
  }

  function setWindowCollapsed(_windowId: string, _isCollapsed: boolean) {
    updateDockWindowItem((current) => ({ ...current, isCollapsed: false }));
  }

  function createDraftChat(windowId: string, projectId: string | null = null) {
    debugThreadSync("dock:create-draft-chat", { projectId, windowId });
    setDockWindowItem({
      draftProjectId: projectId,
      id: `dock-${crypto.randomUUID()}`,
      isCollapsed: false,
      isDraft: true,
      threadId: "",
    });
  }

  function selectThread(windowId: string, threadId: string) {
    debugThreadSync("dock:select-thread", { threadId, windowId });
    if (!threadId) {
      return;
    }
    updateDockWindowItem((current) => ({
      ...current,
      draftProjectId: null,
      isCollapsed: false,
      isDraft: false,
      threadId,
    }));
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
      setThreads((current) => applyThreadCatalogPayload(current, payload));
    } catch {
      // Read receipts are best-effort UI state.
    } finally {
      readReceiptInFlightRef.current.delete(thread.thread_id);
    }
  }

  async function renameThread(threadId: string, title: string) {
    await updateThread({ thread_id: threadId, title });
  }

  async function removeThread(windowId: string, thread: ChatThread) {
    const nextThreads = threadsRef.current.filter((item) => item.thread_id !== thread.thread_id);
    const nextThreadId = nextThreads[0]?.thread_id || "";
    updateDockWindowItem((current) => ({
      ...current,
      isDraft: !nextThreadId,
      threadId: nextThreadId,
    }));
    await deleteThread(thread.thread_id);
    if (nextThreadId) {
      navigateChat(windowId, { thread_id: nextThreadId });
    }
  }

  function closeDock(windowId: string) {
    const selectedWindow = { ...windowItemRef.current, id: windowId, isCollapsed: true };
    if (storageKey) {
      persistWindows(storageKey, [selectedWindow]);
    }
    postDockClose();
  }

  function setDockWindowItem(nextWindow: FloatingChatWindow) {
    windowItemRef.current = nextWindow;
    setWindowItem(nextWindow);
  }

  function updateDockWindowItem(resolveNextWindow: (current: FloatingChatWindow) => FloatingChatWindow) {
    setWindowItem((current) => {
      const nextWindow = resolveNextWindow(current);
      windowItemRef.current = nextWindow;
      return nextWindow;
    });
  }

  return {
    closeDock,
    createDraftChat,
    isReady,
    markThreadReadIfNeeded,
    mode,
    removeThread,
    renameThread,
    runtimeThreadsError,
    runtimeThreadsLoaded,
    selectThread,
    setWindowCollapsed,
    threads,
    windowItem,
  };
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <ChatFloatingDockMount />
  </StrictMode>,
);
