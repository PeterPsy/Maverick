import type { AppReference, ChatMessageAttachment } from "../api/client";
import type { PendingMessage, QueuedMessage } from "./messageState";

const QUEUED_MESSAGES_STORAGE_PREFIX = "maverick.chat.queued-messages.v1";

type PersistedQueuedMessageState = {
  pending: PendingMessage[];
  queued: QueuedMessage[];
};

type PersistedMessage = QueuedMessage & {
  createdAt?: string;
};

export function queueStorageKey(navigationScope: string, conversationKey: string): string {
  return `${QUEUED_MESSAGES_STORAGE_PREFIX}:${navigationScope || "main"}:${conversationKey || "none"}`;
}

export function readPersistedQueuedMessages(storageKey: string): QueuedMessage[] {
  return readPersistedMessageState(storageKey).queued;
}

export function readPersistedPendingMessages(storageKey: string): PendingMessage[] {
  return readPersistedMessageState(storageKey).pending;
}

export function readPersistedRecoverableQueuedMessages(storageKey: string): QueuedMessage[] {
  const state = readPersistedMessageState(storageKey);
  return dedupeMessages([...state.pending, ...state.queued]);
}

export function readPersistedMessageState(storageKey: string): PersistedQueuedMessageState {
  try {
    const rawValue = window.localStorage.getItem(storageKey);
    if (!rawValue) {
      return { pending: [], queued: [] };
    }
    const payload = JSON.parse(rawValue) as { items?: unknown[]; version?: unknown };
    if (payload.version === 1 && Array.isArray(payload.items)) {
      return { pending: [], queued: parsePersistedMessages(payload.items) };
    }
    if (payload.version !== 2) {
      return { pending: [], queued: [] };
    }
    const pending = parsePersistedPendingMessages(
      Array.isArray((payload as { pending?: unknown[] }).pending) ? (payload as { pending: unknown[] }).pending : [],
    );
    const pendingIds = new Set(pending.map((message) => message.clientMessageId));
    const queued = parsePersistedMessages(Array.isArray((payload as { queued?: unknown[] }).queued) ? (payload as { queued: unknown[] }).queued : []).filter(
      (message) => !pendingIds.has(message.clientMessageId),
    );
    return { pending, queued };
  } catch {
    return { pending: [], queued: [] };
  }
}

export function persistQueuedMessages(storageKey: string, queuedMessages: QueuedMessage[]) {
  persistQueuedMessageState(storageKey, { queuedMessages });
}

export function persistQueuedMessageState(
  storageKey: string,
  {
    pendingMessages = [],
    queuedMessages = [],
  }: {
    pendingMessages?: PendingMessage[];
    queuedMessages?: QueuedMessage[];
  },
) {
  try {
    const pending = dedupeMessages(pendingMessages);
    const pendingIds = new Set(pending.map((message) => message.clientMessageId));
    const queued = dedupeMessages(queuedMessages).filter((message) => !pendingIds.has(message.clientMessageId));
    if (!pending.length && !queued.length) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({
        version: 2,
        pending: pending.map(serializableQueuedMessage),
        queued: queued.map(serializableQueuedMessage),
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
  const fromState = readPersistedMessageState(fromStorageKey);
  if (fromState.pending.length || fromState.queued.length) {
    const toStorageKey = queueStorageKey(navigationScope, toConversationKey);
    const toState = readPersistedMessageState(toStorageKey);
    persistQueuedMessageState(toStorageKey, {
      pendingMessages: [...toState.pending, ...fromState.pending],
      queuedMessages: [...toState.queued, ...fromState.queued],
    });
  }
  persistQueuedMessages(fromStorageKey, []);
}

function parsePersistedPendingMessages(items: unknown[]): PendingMessage[] {
  return parsePersistedMessages(items).map((message) => ({
    ...message,
    createdAt: message.createdAt || new Date().toISOString(),
  }));
}

function parsePersistedMessages(items: unknown[]): PersistedMessage[] {
  return dedupeMessages(
    items
      .map((item): PersistedMessage | null => {
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
        const clientSubmissionMetrics = persistedClientSubmissionMetrics(record.clientSubmissionMetrics);
        const invokedSkillIds = persistedSkillIds(record.invokedSkillIds);
        return {
          clientMessageId,
          content,
          ...(typeof record.createdAt === "string" ? { createdAt: record.createdAt } : {}),
          ...(typeof record.clientSubmissionStartedAt === "string"
            ? { clientSubmissionStartedAt: record.clientSubmissionStartedAt }
            : {}),
          ...(clientSubmissionMetrics ? { clientSubmissionMetrics } : {}),
          appReferences: persistedAppReferences(record.appReferences),
          ...(invokedSkillIds.length ? { invokedSkillIds } : {}),
          attachments,
          ...(multiAgentMode ? { multiAgentMode } : {}),
        };
      })
      .filter((item): item is PersistedMessage => Boolean(item)),
  );
}

function persistedSkillIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean))];
}

function dedupeMessages<T extends QueuedMessage>(messages: T[]): T[] {
  const seenClientMessageIds = new Set<string>();
  return messages.filter((message) => {
    if (seenClientMessageIds.has(message.clientMessageId)) {
      return false;
    }
    seenClientMessageIds.add(message.clientMessageId);
    return true;
  });
}

function serializableQueuedMessage(message: QueuedMessage) {
  return {
    ...message,
    attachments: message.attachments.map((attachment) => ({ ...attachment, objectUrl: null })),
  };
}

function persistedMultiAgentMode(value: unknown): QueuedMessage["multiAgentMode"] | undefined {
  return value === "auto" || value === "multi" || value === "group_chat" || value === "off" ? value : undefined;
}

function persistedClientSubmissionMetrics(value: unknown): QueuedMessage["clientSubmissionMetrics"] | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const metrics: QueuedMessage["clientSubmissionMetrics"] = {};
  for (const key of [
    "attachment_upload_ms",
    "prepare_refs_wait_on_submit_ms",
    "prepared_session_wait_on_submit_ms",
    "submit_post_ms",
  ] as const) {
    const metricValue = record[key];
    if (typeof metricValue === "number" && Number.isFinite(metricValue) && metricValue >= 0) {
      metrics[key] = metricValue;
    }
  }
  if (typeof record.prepared_session_ready_before_submit === "boolean") {
    metrics.prepared_session_ready_before_submit = record.prepared_session_ready_before_submit;
  }
  return Object.keys(metrics).length ? metrics : undefined;
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
