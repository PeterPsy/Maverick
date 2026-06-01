import { getWidgetContext } from "../../api/client";
import {
  floatingDockContextFromContent,
  DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE,
  type FloatingDockContext,
} from "./floatingDockState";
import { floatingWidgetSize } from "./floatingLayout";
import {
  FALLBACK_WIDGET_STATE_STORAGE_KEY,
  type FloatingChatWindow,
  widgetStateStorageKey,
} from "./floatingState";

const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";
const FLOATING_STACK_DRAG_IGNORE_SELECTOR =
  'button, a, input, textarea, select, summary, [contenteditable="true"], [role="button"], [role="textbox"], [role="menuitem"]';

export type FloatingWidgetMode = "overlay" | "fixed-right" | "mobile-fullscreen";

export type FloatingWidgetHostContext = {
  mode: FloatingWidgetMode;
  navigationScope: string;
  threadId: string;
  workspaceId: string | null;
};

export async function loadWidgetStateStorageKey(): Promise<string> {
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

export async function loadFloatingDockContext(): Promise<FloatingDockContext> {
  const token = widgetContextToken();
  if (!token) {
    return { mode: "fixed-right", navigationScope: DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE, threadId: "", workspaceId: null };
  }
  try {
    const payload = await getWidgetContext(token);
    return floatingDockContextFromContent(payload.context.content);
  } catch {
    return { mode: "fixed-right", navigationScope: DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE, threadId: "", workspaceId: null };
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
  return { mode, navigationScope, threadId, workspaceId };
}

export function postWidgetSize(windows: FloatingChatWindow[]) {
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

export function postDockClose(widgetId = "chat-floating-dock") {
  window.parent?.postMessage(
    {
      type: "maverick.widget.dock.close",
      owner_app_id: "chat",
      widget_id: widgetId,
    },
    window.location.origin,
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

export function shouldIgnoreFloatingStackDrag(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(FLOATING_STACK_DRAG_IGNORE_SELECTOR));
}

function widgetContextToken(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("context") || new URLSearchParams(window.location.search).get("context") || "";
}

function emptyFloatingWidgetHostContext(): FloatingWidgetHostContext {
  return { mode: "overlay", navigationScope: "", threadId: "", workspaceId: null };
}
