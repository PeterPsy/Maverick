import { useEffect, useRef } from "react";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { persistQueuedMessageState, queueStorageKey } from "../lib/queuedMessages";

export function useQueuedMessagePersistence({
  activeConversationKey,
  isBootstrapping,
  navigationScope,
  queuedMessages,
  pendingUserMessages = [],
}: {
  activeConversationKey: string;
  isBootstrapping: boolean;
  navigationScope: string;
  queuedMessages: QueuedMessage[];
  pendingUserMessages?: PendingMessage[];
}) {
  const hasHydratedQueuedMessagesRef = useRef(false);

  useEffect(() => {
    if (isBootstrapping) {
      return;
    }
    hasHydratedQueuedMessagesRef.current = true;
  }, [isBootstrapping]);

  useEffect(() => {
    if (isBootstrapping || !hasHydratedQueuedMessagesRef.current || !activeConversationKey) {
      return;
    }
    persistQueuedMessageState(queueStorageKey(navigationScope, activeConversationKey), { pendingMessages: pendingUserMessages, queuedMessages });
  }, [activeConversationKey, isBootstrapping, navigationScope, pendingUserMessages, queuedMessages]);
}
