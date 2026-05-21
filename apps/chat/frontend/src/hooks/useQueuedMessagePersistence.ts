import { useEffect, useRef } from "react";
import type { ChatThread } from "../api/client";
import type { QueuedMessage } from "../lib/messageState";
import { persistQueuedMessages, queueStorageKey } from "../lib/queuedMessages";

export function useQueuedMessagePersistence({
  activeThread,
  isBootstrapping,
  navigationScope,
  queuedMessages,
}: {
  activeThread: ChatThread | null;
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
    if (isBootstrapping || !hasHydratedQueuedMessagesRef.current) {
      return;
    }
    persistQueuedMessages(queueStorageKey(navigationScope, activeThread?.thread_id || null), queuedMessages);
  }, [activeThread?.thread_id, isBootstrapping, navigationScope, queuedMessages]);
}
