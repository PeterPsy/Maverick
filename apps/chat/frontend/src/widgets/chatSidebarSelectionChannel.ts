export const CHAT_SIDEBAR_SELECTION_STATE = "maverick.chat.sidebar.selection-state";
export const CHAT_SIDEBAR_SELECTION_QUERY = "maverick.chat.sidebar.selection-query";
export const CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE = "maverick.chat.sidebar.selection-confirm-delete";
export const CHAT_SIDEBAR_SELECTION_CANCEL_DELETE = "maverick.chat.sidebar.selection-cancel-delete";

const CHANNEL_NAME = "maverick.chat.sidebar.selection";
const STORAGE_FALLBACK_KEY = "__maverick_chat_sidebar_selection__";

export type ChatSidebarSelectionStateMessage = {
  app_id: string;
  is_deleting: boolean;
  selected_count: number;
  selected_thread_ids: string[];
  type: typeof CHAT_SIDEBAR_SELECTION_STATE;
  workspace_id?: string;
};

export type ChatSidebarSelectionQueryMessage = {
  app_id: string;
  type: typeof CHAT_SIDEBAR_SELECTION_QUERY;
  workspace_id?: string;
};

export type ChatSidebarSelectionConfirmDeleteMessage = {
  app_id: string;
  request_id: string;
  type: typeof CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE;
  workspace_id?: string;
};

export type ChatSidebarSelectionCancelDeleteMessage = {
  app_id: string;
  request_id: string;
  type: typeof CHAT_SIDEBAR_SELECTION_CANCEL_DELETE;
  workspace_id?: string;
};

export type ChatSidebarSelectionMessage =
  | ChatSidebarSelectionCancelDeleteMessage
  | ChatSidebarSelectionConfirmDeleteMessage
  | ChatSidebarSelectionQueryMessage
  | ChatSidebarSelectionStateMessage;

export type ChatSidebarSelectionChannel = {
  close: () => void;
  post: (message: ChatSidebarSelectionMessage) => void;
};

export function createChatSidebarSelectionChannel(onMessage: (message: ChatSidebarSelectionMessage) => void): ChatSidebarSelectionChannel {
  const broadcastChannel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL_NAME);
  const useStorageFallback = !broadcastChannel && typeof window !== "undefined" && typeof window.addEventListener === "function";

  if (broadcastChannel) {
    broadcastChannel.onmessage = (event) => {
      const message = chatSidebarSelectionMessage(event.data);
      if (message) {
        onMessage(message);
      }
    };
  }

  function handleStorage(event: StorageEvent) {
    if (event.key !== STORAGE_FALLBACK_KEY || !event.newValue) {
      return;
    }
    try {
      const message = chatSidebarSelectionMessage(JSON.parse(event.newValue));
      if (message) {
        onMessage(message);
      }
    } catch {
      // Ignore malformed fallback payloads from stale browser state.
    }
  }

  if (useStorageFallback) {
    window.addEventListener("storage", handleStorage);
  }

  return {
    close: () => {
      broadcastChannel?.close();
      if (useStorageFallback) {
        window.removeEventListener("storage", handleStorage);
      }
    },
    post: (message) => {
      if (broadcastChannel) {
        broadcastChannel.postMessage(message);
        return;
      }
      if (!useStorageFallback) {
        return;
      }
      try {
        window.localStorage.setItem(
          STORAGE_FALLBACK_KEY,
          JSON.stringify({
            ...message,
            emitted_at: Date.now(),
            nonce: randomMessageNonce(),
          }),
        );
      } catch {
        // Selection state is a UI hint; storage fallback failures should not block the widget.
      }
    },
  };
}

export function chatSidebarSelectionMessage(value: unknown): ChatSidebarSelectionMessage | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const payload = value as Partial<ChatSidebarSelectionMessage>;
  if (typeof payload.app_id !== "string" || !payload.app_id.trim()) {
    return null;
  }
  if (payload.workspace_id !== undefined && typeof payload.workspace_id !== "string") {
    return null;
  }
  if (payload.type === CHAT_SIDEBAR_SELECTION_STATE) {
    if (!Array.isArray(payload.selected_thread_ids) || typeof payload.selected_count !== "number") {
      return null;
    }
    return {
      app_id: payload.app_id,
      is_deleting: payload.is_deleting === true,
      selected_count: Math.max(0, Math.floor(payload.selected_count)),
      selected_thread_ids: payload.selected_thread_ids.filter((threadId): threadId is string => typeof threadId === "string"),
      type: CHAT_SIDEBAR_SELECTION_STATE,
      workspace_id: payload.workspace_id,
    };
  }
  if (payload.type === CHAT_SIDEBAR_SELECTION_QUERY) {
    return {
      app_id: payload.app_id,
      type: CHAT_SIDEBAR_SELECTION_QUERY,
      workspace_id: payload.workspace_id,
    };
  }
  if (payload.type === CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE || payload.type === CHAT_SIDEBAR_SELECTION_CANCEL_DELETE) {
    if (typeof payload.request_id !== "string" || !payload.request_id.trim()) {
      return null;
    }
    return {
      app_id: payload.app_id,
      request_id: payload.request_id,
      type: payload.type,
      workspace_id: payload.workspace_id,
    };
  }
  return null;
}

export function isMessageForChatSidebar(message: ChatSidebarSelectionMessage, appId: string, workspaceId: string): boolean {
  if (message.app_id !== appId) {
    return false;
  }
  if (!workspaceId) {
    return !message.workspace_id;
  }
  return !message.workspace_id || message.workspace_id === workspaceId;
}

export function randomMessageNonce(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}:${Math.random().toString(36).slice(2)}`;
}
