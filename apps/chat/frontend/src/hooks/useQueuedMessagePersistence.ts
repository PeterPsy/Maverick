import { useEffect, useRef } from "react";
import type { QueuedMessage } from "../lib/messageState";
import { persistQueuedMessages, queueStorageKey } from "../lib/queuedMessages";

export function useQueuedMessagePersistence({
  activeConversationKey,
  isBootstrapping,
  navigationScope,
  queuedMessages,
}: {
  activeConversationKey: string;
  isBootstrapping: boolean;
  navigationScope: string;
  queuedMessages: QueuedMessage[];
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
    persistQueuedMessages(queueStorageKey(navigationScope, activeConversationKey), queuedMessages);
  }, [activeConversationKey, isBootstrapping, navigationScope, queuedMessages]);
}
