import { activeAppContextFromWidgetContext, type ActiveAppContext } from "../../lib/activeAppContext";
import { getWidgetContext } from "../../api/client";
import { floatingWidgetSize } from "./floatingLayout";
import type { FloatingChatWindow } from "./floatingState";

const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";
export type FloatingWidgetMode = "overlay" | "fixed-right" | "mobile-fullscreen";

export type FloatingWidgetHostContext = {
  activeAppContext: ActiveAppContext | null;
  mode: FloatingWidgetMode;
  navigationScope: string;
  threadId: string;
  workspaceId: string | null;
};

export async function loadFloatingWidgetHostContext(): Promise<FloatingWidgetHostContext> {
  const token = widgetContextToken();
  if (!token) {
    return emptyFloatingWidgetHostContext();
  }
  try {
    const payload = await getWidgetContext(token);
    return floatingWidgetHostContextFromContent(payload.context.content);
  } catch {
    return emptyFloatingWidgetHostContext();
  }
}

export function floatingWidgetHostContextFromContent(content: unknown): FloatingWidgetHostContext {
  const contentRecord = content && typeof content === "object" ? (content as Record<string, unknown>) : {};
  const workspaceId =
    typeof contentRecord.workspace_id === "string" && contentRecord.workspace_id.trim() ? contentRecord.workspace_id.trim() : null;
  const nestedPayload =
    contentRecord.payload && typeof contentRecord.payload === "object" ? (contentRecord.payload as Record<string, unknown>) : {};
  const rawMode = typeof nestedPayload.mode === "string" ? nestedPayload.mode.trim() : "";
  const mode: FloatingWidgetMode =
    rawMode === "fixed-right" || rawMode === "mobile-fullscreen" || rawMode === "overlay" ? rawMode : "overlay";
  const navigationScope =
    typeof nestedPayload.navigation_scope === "string" && nestedPayload.navigation_scope.trim()
      ? nestedPayload.navigation_scope.trim()
      : "";
  const threadId = typeof nestedPayload.thread_id === "string" && nestedPayload.thread_id.trim() ? nestedPayload.thread_id.trim() : "";
  return { activeAppContext: activeAppContextFromWidgetContext({ content }), mode, navigationScope, threadId, workspaceId };
}

export function postWidgetSize(windows: FloatingChatWindow[]) {
  window.parent?.postMessage(
    {
      ...floatingWidgetSize(windows),
      type: "maverick.widget.resize",
      owner_app_id: "chat",
      widget_id: "chat-floating",
    },
    "*",
  );
}

export function postDockClose(widgetId = "chat-floating") {
  window.parent?.postMessage(
    {
      type: "maverick.widget.dock.close",
      owner_app_id: "chat",
      widget_id: widgetId,
    },
    "*",
  );
}

export function debugThreadSync(label: string, detail: Record<string, unknown> = {}) {
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

function widgetContextToken(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("context") || new URLSearchParams(window.location.search).get("context") || "";
}

function emptyFloatingWidgetHostContext(): FloatingWidgetHostContext {
  return { activeAppContext: null, mode: "overlay", navigationScope: "", threadId: "", workspaceId: null };
}
