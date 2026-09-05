import { useEffect, useRef } from "react";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { clearQueuedMessageMemory, rememberQueuedMessageState, queueMemoryKey } from "../lib/queuedMessages";

export function useQueuedMessageMemory({
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
  useEffect(() => () => clearQueuedMessageMemory(navigationScope), [navigationScope]);
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
    rememberQueuedMessageState(queueMemoryKey(navigationScope, activeConversationKey), { pendingMessages: pendingUserMessages, queuedMessages });
  }, [activeConversationKey, isBootstrapping, navigationScope, pendingUserMessages, queuedMessages]);
}
