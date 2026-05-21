import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";
import { deleteThread, markThreadRead, updateThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { isThreadUnread } from "../chat-sidebar/sections";
import {
  horizontalDragScrollLeft,
  isHorizontalDragIntent,
  isVerticalDragIntent,
} from "./floatingLayout";
import {
  type FloatingChatWindow,
  createWindow,
  persistWindows,
  readPersistedOrDefaultWindows,
  reconcileWindowsWithThreads,
} from "./floatingState";
import { debugThreadSync, loadWidgetStateStorageKey, postWidgetSize, shouldIgnoreFloatingStackDrag } from "./floatingWidgetRuntime";

type FloatingStackDragState = {
  isDragging: boolean;
  pointerId: number;
  scrollLeft: number;
  startX: number;
  startY: number;
};

export function useFloatingWindows() {
  const [storageKey, setStorageKey] = useState<string | null>(null);
  const [isWindowStateReady, setIsWindowStateReady] = useState(false);
  const [runtimeThreadsLoaded, setRuntimeThreadsLoaded] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [runtimeThreadsError, setRuntimeThreadsError] = useState<string | null>(null);
  const [windows, setWindows] = useState<FloatingChatWindow[]>([]);
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const stackDragRef = useRef<FloatingStackDragState | null>(null);
  const stackRef = useRef<HTMLDivElement | null>(null);
  const threadsRef = useRef(threads);
  const windowsRef = useRef(windows);

  useRuntimeThreads({ onSnapshot: () => setRuntimeThreadsLoaded(true), setError: setRuntimeThreadsError, setThreads });

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
    setWindows((current) =>
      current.map((windowItem) => (windowItem.threadId === thread.thread_id ? { ...windowItem, threadId: nextThreadId } : windowItem)),
    );
    await deleteThread(thread.thread_id);
    if (nextThreadId) {
      navigateChat(windowId, { thread_id: nextThreadId });
    }
  }

  function startStackDrag(event: ReactPointerEvent<HTMLDivElement>) {
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

  function moveStackDrag(event: ReactPointerEvent<HTMLDivElement>) {
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

  function endStackDrag(event: ReactPointerEvent<HTMLDivElement>) {
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

  return {
    closeWindow,
    createDraftChat,
    isWindowStateReady,
    markThreadReadIfNeeded,
    removeThread,
    renameThread,
    runtimeThreadsError,
    runtimeThreadsLoaded,
    selectThread,
    setWindowCollapsed,
    stackHandlers: {
      onLostPointerCapture: endStackDrag,
      onPointerCancel: endStackDrag,
      onPointerDown: startStackDrag,
      onPointerMove: moveStackDrag,
      onPointerUp: endStackDrag,
    },
    stackRef,
    threads,
    windows,
  };
}
