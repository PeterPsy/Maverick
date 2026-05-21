import { getWidgetContext } from "../../api/client";
import { floatingWidgetSize } from "./floatingLayout";
import {
  FALLBACK_WIDGET_STATE_STORAGE_KEY,
  type FloatingChatWindow,
  widgetStateStorageKey,
} from "./floatingState";

const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";
const FLOATING_STACK_DRAG_IGNORE_SELECTOR =
  'button, a, input, textarea, select, summary, [contenteditable="true"], [role="button"], [role="textbox"], [role="menuitem"]';

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
