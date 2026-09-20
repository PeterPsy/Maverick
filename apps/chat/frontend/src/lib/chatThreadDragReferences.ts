import type { DragEvent } from "react";
import type { AppEntityReference, ChatThread } from "../api/client";
import { referenceKey, type MentionItem } from "./mentions";

export const CHAT_THREAD_DRAG_DATA_TYPE = "application/x-maverick-chat-thread";

const CHAT_APP_ID = "chat";
const CHAT_THREAD_SUMMARY = "Chat conversation available through the authorized runtime transcript reader";

export type ChatThreadDragPayload = {
  owner_app_id: string;
  thread_id: string;
  title: string;
};

type ChatThreadDragDataTransfer = Pick<DataTransfer, "setData"> & {
  effectAllowed?: DataTransfer["effectAllowed"];
};

export function chatThreadDragPayload(thread: ChatThread): ChatThreadDragPayload {
  return {
    owner_app_id: CHAT_APP_ID,
    thread_id: thread.thread_id,
    title: normalizedTitle(thread.title),
  };
}

export function writeChatThreadDragData(
  dataTransfer: ChatThreadDragDataTransfer,
  payload: ChatThreadDragPayload,
): void {
  dataTransfer.setData(CHAT_THREAD_DRAG_DATA_TYPE, JSON.stringify(payload));
  dataTransfer.effectAllowed = "copy";
}

export function hasChatThreadReferenceDragData(
  dataTransfer: Pick<DataTransfer, "types">,
): boolean {
  return Array.from(dataTransfer.types || [])
    .map((type) => String(type).toLowerCase())
    .includes(CHAT_THREAD_DRAG_DATA_TYPE);
}

export function readChatThreadDragData(
  dataTransfer: Pick<DataTransfer, "getData">,
): ChatThreadDragPayload | null {
  const rawPayload = dataTransfer.getData(CHAT_THREAD_DRAG_DATA_TYPE);
  if (!rawPayload) {
    return null;
  }
  try {
    return normalizeChatThreadDragPayload(JSON.parse(rawPayload));
  } catch {
    return null;
  }
}

export function chatThreadMentionItemsFromDataTransfer(
  dataTransfer: Pick<DataTransfer, "getData">,
): MentionItem[] {
  const payload = readChatThreadDragData(dataTransfer);
  return payload ? [chatThreadMentionItem(chatThreadReference(payload))] : [];
}

export function chatThreadReference(thread: Pick<ChatThread, "thread_id" | "title">): AppEntityReference {
  const threadId = normalizeReferenceId(thread.thread_id);
  const title = normalizedTitle(thread.title);
  return {
    type: "entity",
    app_id: CHAT_APP_ID,
    entity_type: "thread",
    entity_id: threadId,
    label: title,
    summary: CHAT_THREAD_SUMMARY,
    deep_link: `/app/${CHAT_APP_ID}/threads/${encodeURIComponent(threadId)}`,
  };
}

export function attachChatThreadDragImage(event: DragEvent<HTMLElement>, title: string): void {
  if (!event.dataTransfer.setDragImage) {
    return;
  }
  const dragImage = document.createElement("div");
  dragImage.className = "bs-chat-thread-drag-image";
  dragImage.setAttribute("aria-hidden", "true");

  const icon = document.createElement("span");
  icon.className = "material-symbols-rounded";
  icon.textContent = "chat_bubble";

  const label = document.createElement("span");
  label.className = "bs-chat-thread-drag-image__label";
  label.textContent = normalizedTitle(title);

  dragImage.append(icon, label);
  document.body.appendChild(dragImage);
  event.dataTransfer.setDragImage(dragImage, 22, 22);
  window.setTimeout(() => dragImage.remove(), 0);
}

function chatThreadMentionItem(reference: AppEntityReference): MentionItem {
  return {
    id: referenceKey(reference),
    label: reference.label,
    description: `chat · thread · ${reference.summary}`,
    kind: "entity",
    reference,
  };
}

function normalizeChatThreadDragPayload(payload: unknown): ChatThreadDragPayload | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const ownerAppId = normalizeText(record.owner_app_id);
  const threadId = normalizeReferenceId(record.thread_id);
  const title = normalizedTitle(record.title);
  if (ownerAppId !== CHAT_APP_ID || !threadId) {
    return null;
  }
  return {
    owner_app_id: ownerAppId,
    thread_id: threadId,
    title,
  };
}

function normalizeReferenceId(value: unknown): string {
  const normalized = normalizeText(value);
  if (!normalized || normalized.length > 240 || !/^[A-Za-z0-9._:-]+$/.test(normalized)) {
    return "";
  }
  return normalized;
}

function normalizedTitle(value: unknown): string {
  return normalizeText(value).replace(/[\[\]]/g, "").slice(0, 240) || "Chat conversation";
}

function normalizeText(value: unknown): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}
