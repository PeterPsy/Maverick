import type { FloatingChatWindow } from "./floatingState";

export const DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE = "chat-floating-dock";

export type FloatingDockContext = {
  mode: "fixed-right" | "mobile-fullscreen";
  navigationScope: string;
  threadId: string;
  workspaceId: string | null;
};

export type FloatingDockThreadMessage = {
  active_thread_id?: unknown;
  navigation_scope?: unknown;
  owner_app_id?: unknown;
  type?: unknown;
};

export type FloatingDockWidgetMessage = FloatingDockThreadMessage & {
  context?: { content?: unknown };
  widget_id?: unknown;
};

export function floatingDockContextFromContent(content: unknown): FloatingDockContext {
  const contentRecord = content && typeof content === "object" ? (content as Record<string, unknown>) : {};
  const workspaceId =
    typeof contentRecord.workspace_id === "string" && contentRecord.workspace_id.trim() ? contentRecord.workspace_id.trim() : null;
  const nestedPayload =
    contentRecord.payload && typeof contentRecord.payload === "object" ? (contentRecord.payload as Record<string, unknown>) : {};
  const navigationScope =
    typeof nestedPayload.navigation_scope === "string" && nestedPayload.navigation_scope.trim()
      ? nestedPayload.navigation_scope.trim()
      : DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE;
  const threadId = typeof nestedPayload.thread_id === "string" && nestedPayload.thread_id.trim() ? nestedPayload.thread_id.trim() : "";
  const mode = nestedPayload.mode === "mobile-fullscreen" ? "mobile-fullscreen" : "fixed-right";
  return { mode, navigationScope, threadId, workspaceId };
}

export function floatingDockWindowFromContext(context: FloatingDockContext, persistedWindows: readonly FloatingChatWindow[] = []): FloatingChatWindow {
  const threadId = context.threadId || preferredPersistedThreadId(persistedWindows);
  return {
    draftProjectId: null,
    id: context.navigationScope,
    isCollapsed: false,
    isDraft: !threadId,
    threadId,
  };
}

export function floatingDockWindowAfterActiveThreadChanged(
  current: FloatingChatWindow,
  payload: FloatingDockThreadMessage,
): FloatingChatWindow {
  if (payload.type !== "maverick.chat.active-thread-changed" || payload.owner_app_id !== "chat") {
    return current;
  }
  const navigationScope = typeof payload.navigation_scope === "string" ? payload.navigation_scope.trim() : "";
  if (!navigationScope || navigationScope !== current.id) {
    return current;
  }
  const threadId = typeof payload.active_thread_id === "string" && payload.active_thread_id.trim() ? payload.active_thread_id.trim() : "";
  if (!threadId) {
    return current;
  }
  return {
    ...current,
    draftProjectId: null,
    isCollapsed: false,
    isDraft: false,
    threadId,
  };
}

export function floatingDockWindowAfterWidgetMessage(
  current: FloatingChatWindow,
  payload: FloatingDockWidgetMessage,
): FloatingChatWindow {
  if (payload.owner_app_id !== "chat") {
    return current;
  }
  if (payload.type === "maverick.widget.context-changed" && payload.widget_id === DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE) {
    const context = floatingDockContextFromContent(payload.context?.content);
    if (context.threadId) {
      return floatingDockWindowFromContext(context);
    }
    return {
      ...current,
      id: context.navigationScope,
      isCollapsed: false,
    };
  }
  if (payload.type === "maverick.chat.active-thread-changed") {
    return floatingDockWindowAfterActiveThreadChanged(current, payload);
  }
  return current;
}

function preferredPersistedThreadId(windows: readonly FloatingChatWindow[]): string {
  const newestFirst = [...windows].reverse();
  return (
    newestFirst.find((windowItem) => !windowItem.isDraft && windowItem.threadId)?.threadId ||
    newestFirst.find((windowItem) => windowItem.threadId)?.threadId ||
    ""
  );
}
