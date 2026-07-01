import type { AppReference, ChatMessageAttachment } from "../api/client";
import type { QueuedMessage } from "./messageState";

const QUEUED_MESSAGES_STORAGE_PREFIX = "maverick.chat.queued-messages.v1";

export function queueStorageKey(navigationScope: string, conversationKey: string): string {
  return `${QUEUED_MESSAGES_STORAGE_PREFIX}:${navigationScope || "main"}:${conversationKey || "none"}`;
}

export function readPersistedQueuedMessages(storageKey: string): QueuedMessage[] {
  try {
    const rawValue = window.localStorage.getItem(storageKey);
    if (!rawValue) {
      return [];
    }
    const payload = JSON.parse(rawValue) as { items?: unknown[]; version?: unknown };
    if (payload.version !== 1 || !Array.isArray(payload.items)) {
      return [];
    }
    return payload.items
      .map((item): QueuedMessage | null => {
        if (!item || typeof item !== "object") {
          return null;
        }
        const record = item as Record<string, unknown>;
        const clientMessageId = typeof record.clientMessageId === "string" ? record.clientMessageId : "";
        const content = typeof record.content === "string" ? record.content : "";
        const attachments = Array.isArray(record.attachments) ? record.attachments.filter(isPersistedMessageAttachment) : [];
        if (!clientMessageId || (!content.trim() && !attachments.length)) {
          return null;
        }
        const multiAgentMode = persistedMultiAgentMode(record.multiAgentMode);
        return {
          clientMessageId,
          content,
          appReferences: persistedAppReferences(record.appReferences),
          attachments,
          ...(multiAgentMode ? { multiAgentMode } : {}),
        };
      })
      .filter((item): item is QueuedMessage => Boolean(item));
  } catch {
    return [];
  }
}

export function persistQueuedMessages(storageKey: string, queuedMessages: QueuedMessage[]) {
  try {
    if (!queuedMessages.length) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({
        version: 1,
        items: queuedMessages.map((message) => ({
          ...message,
          attachments: message.attachments.map((attachment) => ({ ...attachment, objectUrl: null })),
        })),
      }),
    );
  } catch {
    // Queue persistence is best-effort; in-memory sending remains the source of truth.
  }
}

export function migratePersistedQueuedMessages(navigationScope: string, fromConversationKey: string, toConversationKey: string) {
  if (!fromConversationKey || !toConversationKey || fromConversationKey === toConversationKey) {
    return;
  }
  const fromStorageKey = queueStorageKey(navigationScope, fromConversationKey);
  const queuedMessages = readPersistedQueuedMessages(fromStorageKey);
  if (queuedMessages.length) {
    const toStorageKey = queueStorageKey(navigationScope, toConversationKey);
    persistQueuedMessages(toStorageKey, [...readPersistedQueuedMessages(toStorageKey), ...queuedMessages]);
  }
  persistQueuedMessages(fromStorageKey, []);
}

function persistedMultiAgentMode(value: unknown): QueuedMessage["multiAgentMode"] | undefined {
  return value === "auto" || value === "multi" || value === "group_chat" || value === "off" ? value : undefined;
}

function persistedAppReferences(value: unknown): AppReference[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map(persistedAppReference)
    .filter((item) => (item.type === "app" ? Boolean(item.app_id) : Boolean(item.app_id && item.entity_type && item.entity_id)));
}

function persistedAppReference(item: Record<string, unknown>): AppReference {
  const appId = typeof item.app_id === "string" ? item.app_id : "";
  if (item.type === "entity") {
    return {
      type: "entity",
      app_id: appId,
      entity_type: typeof item.entity_type === "string" ? item.entity_type : "",
      entity_id: typeof item.entity_id === "string" ? item.entity_id : "",
      label: typeof item.label === "string" ? item.label : "",
      summary: typeof item.summary === "string" ? item.summary : undefined,
      deep_link: typeof item.deep_link === "string" ? item.deep_link : undefined,
      exists: typeof item.exists === "boolean" ? item.exists : undefined,
    };
  }
  return {
    type: "app",
    app_id: appId,
    label: typeof item.label === "string" ? item.label : undefined,
  };
}

function isPersistedMessageAttachment(value: unknown): value is ChatMessageAttachment {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.name === "string" && typeof record.size === "number" && typeof record.type === "string";
}
