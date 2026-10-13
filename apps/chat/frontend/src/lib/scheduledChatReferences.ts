import { startMaverickReferencePointerDrag } from "@maverick/pwa-cache";
import type { PointerEvent } from "react";
import type { AppEntityReference } from "../api/client";
import type { ScheduledChat } from "../api/scheduledChats";
import { referenceKey, type MentionItem } from "./mentions";

export const SCHEDULED_CHAT_DRAG_TYPE = "application/x-maverick-scheduled-chat";

export function scheduledChatReference(chat: Pick<ScheduledChat, "id" | "title">): AppEntityReference {
  return { type: "entity", app_id: "chat", entity_type: "scheduled_chat", entity_id: chat.id,
    label: chat.title.replace(/[\[\]]/g, "").slice(0, 160),
    summary: "Scheduled skill-block graph. Read and manage it with the chat_scheduled tool.",
    deep_link: `/app/chat/scheduled/${encodeURIComponent(chat.id)}` };
}

export function scheduledChatDragData(chat: Pick<ScheduledChat, "id" | "title">) {
  return JSON.stringify({ owner_app_id: "chat", id: chat.id, title: chat.title });
}

export function scheduledChatMentionItems(transfer: Pick<DataTransfer, "getData">): MentionItem[] {
  try {
    const raw = transfer.getData(SCHEDULED_CHAT_DRAG_TYPE);
    if (!raw || raw.length > 2048) return [];
    const data: unknown = JSON.parse(raw);
    if (!data || typeof data !== "object") return [];
    const item = data as Record<string, unknown>;
    if (item.owner_app_id !== "chat" || typeof item.id !== "string" || !/^[A-Za-z0-9_-]{1,80}$/.test(item.id)
      || typeof item.title !== "string" || item.title.length > 160) return [];
    const reference = scheduledChatReference({ id: item.id, title: item.title });
    return [{ id: referenceKey(reference), label: reference.label, description: "chat · Scheduled task", kind: "entity", reference }];
  } catch { return []; }
}

/** Pointer transport crosses isolated app frames; the native payload also works within Chat. */
export function startScheduledChatPointerDrag(event: PointerEvent<HTMLElement>, chat: Pick<ScheduledChat, "id" | "title">, onDraggingChange: (dragging: boolean) => void = () => undefined) {
  if (event.target instanceof Element && event.target.closest("button, input, textarea, select, a") && !event.target.closest("[data-scheduled-drag-open]")) return;
  return startMaverickReferencePointerDrag(event.nativeEvent, event.currentTarget, () => ({
    label: chat.title, transfer: { type: SCHEDULED_CHAT_DRAG_TYPE, data: scheduledChatDragData(chat) },
  }), onDraggingChange);
}
