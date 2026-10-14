import { activeAppContextFromWidgetContext, type ActiveAppContext } from "../../lib/activeAppContext";
import { useEffect, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";
import { applyThreadCatalogPayload, markThreadRead } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { isThreadUnread } from "../chat-sidebar/sections";
import {
  type FloatingChatWindow, createWindow, persistWindows, readPersistedOrDefaultWindows,
  FALLBACK_WIDGET_STATE_STORAGE_KEY, widgetStateStorageKey, reconcileWindowsWithThreads,
} from "./floatingState";
import {
  floatingWidgetHostContextFromContent, loadFloatingWidgetHostContext, postDockClose,
  postWidgetSize, type FloatingWidgetMode,
} from "./floatingWidgetRuntime";

export function useFloatingWindows() {
  const [storageKey, setStorageKey] = useState<string | null>(null);
  const [isWindowStateReady, setIsWindowStateReady] = useState(false);
  const [runtimeThreadsLoaded, setRuntimeThreadsLoaded] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [runtimeThreadsError, setRuntimeThreadsError] = useState<string | null>(null);
  const [windows, setWindows] = useState<FloatingChatWindow[]>([]);
  const [activeAppContext, setActiveAppContext] = useState<ActiveAppContext | null>(null);
  const latestContextRef = useRef<unknown>(null);
  const [hostMode, setHostMode] = useState<FloatingWidgetMode>("overlay");
  const [hostNavigationScope, setHostNavigationScope] = useState("");
  const readReceiptInFlightRef = useRef(new Set<string>());
  const stackRef = useRef<HTMLDivElement | null>(null);
  const threadsRef = useRef(threads);
  const windowsRef = useRef(windows);
  threadsRef.current = threads;
  windowsRef.current = windows;

  useRuntimeThreads({ onSnapshot: () => setRuntimeThreadsLoaded(true), onThreadsDeleted: resetDeletedThreads, setError: setRuntimeThreadsError, setThreads });

  useEffect(() => {
    if (isWindowStateReady && runtimeThreadsLoaded) {
      setWindows((current) => reconcileWindowsWithThreads(current.map((item) => {
        const latest = threads.find((thread) => thread.thread_id === item.threadId);
        return latest ? { ...item, selectedThread: latest } : item;
      }), threads));
    }
  }, [isWindowStateReady, runtimeThreadsLoaded, threads]);

  useEffect(() => {
    if (!isWindowStateReady || !storageKey) return;
    persistWindows(storageKey, windows);
    if (hostMode === "overlay") postWidgetSize(windows);
  }, [hostMode, isWindowStateReady, storageKey, windows]);

  useEffect(() => {
    let cancelled = false;
    void loadFloatingWidgetHostContext().then((initialContext) => {
      if (cancelled) return;
      const context = latestContextRef.current ? floatingWidgetHostContextFromContent(latestContextRef.current) : initialContext;
      setActiveAppContext(latestContextRef.current ? activeAppContextFromWidgetContext({ content: latestContextRef.current }) : initialContext.activeAppContext);
      const key = context.workspaceId ? widgetStateStorageKey(context.workspaceId) : FALLBACK_WIDGET_STATE_STORAGE_KEY;
      let restored = readPersistedOrDefaultWindows(key);
      // Apply a launch selection once. Later context/theme updates are not navigation.
      if (context.navigationScope && context.threadId) {
        if (!restored.some((item) => item.id === context.navigationScope)) {
          restored = [...restored, { ...createWindow(context.threadId), id: context.navigationScope }];
        }
      }
      setHostMode(context.mode);
      setHostNavigationScope(context.navigationScope);
      setStorageKey(key);
      setWindows(restored);
      setIsWindowStateReady(true);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    function handleWidgetMessage(event: MessageEvent) {
      // The authenticated host relay delivers messages into the widget document.
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
      const payload = event.data;
      if (payload.owner_app_id !== "chat") return;
      if (payload.type === "loopino.widget.context-changed" && payload.widget_id === "chat-floating") {
        latestContextRef.current = payload.context?.content;
        if (!isWindowStateReady) return;
        setActiveAppContext(activeAppContextFromWidgetContext(payload.context || {}));
        const context = floatingWidgetHostContextFromContent(payload.context?.content);
        setHostMode(context.mode);
        // Selection belongs to explicit window actions and scoped navigation.
        // A host context refresh can carry an older scope/thread after a new
        // draft was opened; it must never change the selected window.

        return;
      }
      if (isWindowStateReady && payload.type === "loopino.chat.active-thread-changed") {
        const scope = typeof payload.navigation_scope === "string" ? payload.navigation_scope : "";
        const threadId = typeof payload.active_thread_id === "string" ? payload.active_thread_id : "";
        if (!scope || !threadId) return;
        setWindows((current) => reconcileWindowsWithThreads(current, threadsRef.current, threadId, scope));
      }
    }
    window.addEventListener("message", handleWidgetMessage);
    return () => window.removeEventListener("message", handleWidgetMessage);
  }, [isWindowStateReady]);

  function focusWindow(windowId: string) {
    requestAnimationFrame(() => {
      const slot = stackRef.current?.querySelector(`[data-window-id="${CSS.escape(windowId)}"]`);
      slot?.scrollIntoView({ block: "nearest", inline: "nearest" });
      slot?.querySelector<HTMLButtonElement>(".chat-floating-thread-menu__trigger")?.focus({ preventScroll: true });
    });
  }

  function revealWindow(windowId: string) {
    setHostNavigationScope(windowId);
    setWindows((current) => current.map((item) => item.id === windowId ? { ...item, isCollapsed: false } : item));
    focusWindow(windowId);
  }

  function setWindowCollapsed(windowId: string, isCollapsed: boolean) {
    if (!isCollapsed) { revealWindow(windowId); return; }
    setWindows((current) => current.map((item) => item.id === windowId ? { ...item, isCollapsed: true } : item));
  }

  function createDraftChat(_windowId: string, projectId: string | null = null) {
    const next = createWindow("", true, projectId);
    setWindows((current) => [...current, next]);
    setHostNavigationScope(next.id);
    focusWindow(next.id);
  }

  function dockWindow(windowId: string) {
    const selected = windowsRef.current.find((item) => item.id === windowId);
    if (!selected) return;
    setHostNavigationScope(selected.id);
    window.parent.postMessage({
      type: "loopino.widget.dock.open", owner_app_id: "chat", widget_id: "chat-floating", placement: "right",
      params: { navigation_scope: selected.id, thread_id: selected.threadId },
    }, "*");
  }

  function selectThread(windowId: string, threadId: string, selectedThread?: ChatThread) {
    if (!threadId) return;
    const existing = windowsRef.current.find((item) => item.threadId === threadId && !item.isDraft);
    const next = existing || { ...createWindow(threadId), selectedThread: selectedThread || threadsRef.current.find((thread) => thread.thread_id === threadId) };
    if (selectedThread) setThreads((current) => applyThreadCatalogPayload(current, { changed_thread: selectedThread }));
    setWindows((current) => (existing ? current : [...current, next]).map((item) =>
      item.id === next.id ? { ...item, isCollapsed: false }
        : item.id === windowId ? { ...item, isCollapsed: true } : item));
    setHostNavigationScope(next.id);
    focusWindow(next.id);
  }

  async function markThreadReadIfNeeded(thread: ChatThread) {
    if (!isThreadUnread(thread) || readReceiptInFlightRef.current.has(thread.thread_id)) return;
    readReceiptInFlightRef.current.add(thread.thread_id);
    try {
      const payload = await markThreadRead(thread.thread_id);
      setThreads((current) => applyThreadCatalogPayload(current, payload));
    } catch {
      // Read receipts do not block navigation; failed receipts remain retryable.
    } finally { readReceiptInFlightRef.current.delete(thread.thread_id); }
  }

  function resetDeletedThreads(threadIds: string[], projectId?: string) {
    const deleted = new Set(threadIds);
    setThreads((current) => current.filter((item) => !deleted.has(item.thread_id) && (!projectId || item.project_id !== projectId)));
    setWindows((current) => current.map((item) => deleted.has(item.threadId) || (projectId && item.selectedThread?.thread_id === item.threadId && item.selectedThread.project_id === projectId)
      ? { ...item, draftProjectId: null, draftRequestId: crypto.randomUUID(), isDraft: true, threadId: "", selectedThread: undefined } : item));
  }

  return {
    closeWindow: (windowId: string) => setWindowCollapsed(windowId, true),
    closeDock: () => postDockClose(), activeAppContext, createDraftChat, dockWindow, hostMode, hostNavigationScope,
    isWindowStateReady, markThreadReadIfNeeded, resetDeletedThreads,
    runtimeThreadsError, runtimeThreadsLoaded, selectThread, setWindowCollapsed, stackRef, threads, windows,
  };
}
