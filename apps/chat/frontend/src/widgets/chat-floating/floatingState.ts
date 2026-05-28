export const WIDGET_STATE_STORAGE_KEY_PREFIX = "maverick.chat.floating-widget.state.v1";
export const FALLBACK_WIDGET_STATE_STORAGE_KEY = `${WIDGET_STATE_STORAGE_KEY_PREFIX}:global`;

export type FloatingChatWindow = {
  draftProjectId: string | null;
  id: string;
  isDraft: boolean;
  isCollapsed: boolean;
  threadId: string;
};

export type PersistedFloatingChatWindow = {
  draftProjectId?: string | null;
  id: string;
  isDraft?: boolean;
  isCollapsed: boolean;
  threadId: string;
};

export type PersistedFloatingWidgetState = {
  version: 1;
  windows: PersistedFloatingChatWindow[];
};

type ThreadLike = {
  thread_id: string;
};

type WindowStorage = Pick<Storage, "getItem" | "setItem">;

export function createWindow(threadId = "", isDraft = false, draftProjectId: string | null = null): FloatingChatWindow {
  return {
    draftProjectId,
    id: `window-${randomWindowId()}`,
    isDraft,
    isCollapsed: false,
    threadId,
  };
}

export function widgetStateStorageKey(workspaceId: string) {
  return `${WIDGET_STATE_STORAGE_KEY_PREFIX}:${workspaceId}`;
}

export function defaultFloatingWindows(): FloatingChatWindow[] {
  return [createWindow()];
}

export function readPersistedWindows(storageKey: string, storage = defaultWindowStorage()): FloatingChatWindow[] | null {
  if (!storage) {
    return null;
  }
  try {
    const rawValue = storage.getItem(storageKey);
    if (!rawValue) {
      return null;
    }
    const payload = JSON.parse(rawValue) as Partial<PersistedFloatingWidgetState>;
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
      .filter((windowItem): windowItem is FloatingChatWindow => Boolean(windowItem));
    return windows.length > 0 ? windows : null;
  } catch {
    return null;
  }
}

export function readPersistedOrDefaultWindows(
  storageKey: string,
  { migrateFromFallback = true, storage = defaultWindowStorage() }: { migrateFromFallback?: boolean; storage?: WindowStorage | null } = {},
): FloatingChatWindow[] {
  return (
    readPersistedWindows(storageKey, storage) ||
    (migrateFromFallback && storageKey !== FALLBACK_WIDGET_STATE_STORAGE_KEY
      ? readPersistedWindows(FALLBACK_WIDGET_STATE_STORAGE_KEY, storage)
      : null) ||
    defaultFloatingWindows()
  );
}

export function persistWindows(storageKey: string, windows: FloatingChatWindow[], storage = defaultWindowStorage()) {
  if (!storage) {
    return;
  }
  try {
    const payload: PersistedFloatingWidgetState = {
      version: 1,
      windows: windows.map((windowItem) => ({
        draftProjectId: windowItem.draftProjectId,
        id: windowItem.id,
        isDraft: windowItem.isDraft,
        isCollapsed: windowItem.isCollapsed,
        threadId: windowItem.threadId,
      })),
    };
    storage.setItem(storageKey, JSON.stringify(payload));
  } catch {
    // Persistence is best-effort UI state; runtime behavior must keep working.
  }
}

export function reconcileWindowsWithThreads(
  windows: FloatingChatWindow[],
  threads: ThreadLike[],
  preferredThreadId = "",
  navigationScope = "",
) {
  const firstThreadId = threads[0]?.thread_id || "";
  const threadIds = new Set(threads.map((thread) => thread.thread_id));
  return windows.map((windowItem) => {
    const hasValidThread = Boolean(windowItem.threadId && threadIds.has(windowItem.threadId));
    if (hasValidThread && (windowItem.isDraft || windowItem.draftProjectId)) {
      return { ...windowItem, draftProjectId: null, isDraft: false };
    }
    if (windowItem.isDraft && (!navigationScope || windowItem.id !== navigationScope)) {
      return windowItem;
    }
    if (windowItem.isDraft && navigationScope === windowItem.id && !preferredThreadId) {
      return windowItem;
    }
    if (!navigationScope) {
      if (!windowItem.threadId && firstThreadId) {
        return { ...windowItem, threadId: firstThreadId };
      }
      return !windowItem.threadId || threadIds.has(windowItem.threadId) ? windowItem : { ...windowItem, isDraft: true };
    }
    if (navigationScope && windowItem.id !== navigationScope) {
      if (!windowItem.threadId && firstThreadId) {
        return { ...windowItem, threadId: firstThreadId };
      }
      return !windowItem.threadId || threadIds.has(windowItem.threadId) ? windowItem : { ...windowItem, isDraft: true };
    }
    const nextThreadId =
      preferredThreadId && threadIds.has(preferredThreadId)
        ? preferredThreadId
        : windowItem.threadId && threadIds.has(windowItem.threadId)
          ? windowItem.threadId
          : firstThreadId;
    return nextThreadId ? { ...windowItem, draftProjectId: null, isDraft: false, threadId: nextThreadId } : { ...windowItem, isDraft: true };
  });
}

function windowFromPersistedState(windowItem: PersistedFloatingChatWindow): FloatingChatWindow {
  return {
    draftProjectId: typeof windowItem.draftProjectId === "string" ? windowItem.draftProjectId : null,
    id: windowItem.id,
    isDraft: windowItem.isDraft === true,
    isCollapsed: windowItem.isCollapsed,
    threadId: windowItem.threadId,
  };
}

function defaultWindowStorage(): WindowStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function randomWindowId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
