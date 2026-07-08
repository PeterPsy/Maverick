import { Dispatch, SetStateAction, useRef } from "react";
import { ChatThread, applyThreadCatalogPayload, markThreadRead } from "../api/client";

type UseChatReadReceiptsParams = {
  activeThread: ChatThread | null;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

export function useChatReadReceipts({ activeThread, setActiveThread, setThreads }: UseChatReadReceiptsParams) {
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());

  function handleChatRootPointerDown() {
    void markActiveThreadReadIfNeeded(activeThread);
  }

  async function markActiveThreadReadIfNeeded(thread: ChatThread | null) {
    if (!thread?.has_unread_completed_response || readReceiptInFlightRef.current.has(thread.thread_id)) {
      return;
    }
    readReceiptInFlightRef.current.add(thread.thread_id);
    setActiveThread((current) => (current?.thread_id === thread.thread_id ? { ...current, has_unread_completed_response: false } : current));
    setThreads((current) =>
      current.map((item) => (item.thread_id === thread.thread_id ? { ...item, has_unread_completed_response: false } : item)),
    );
    try {
      const payload = await markThreadRead(thread.thread_id);
      setThreads((current) => applyThreadCatalogPayload(current, payload));
      setActiveThread((current) => (current?.thread_id === payload.thread.thread_id ? payload.thread : current));
    } catch {
      // Reading an open chat should not be blocked by a best-effort receipt.
    } finally {
      readReceiptInFlightRef.current.delete(thread.thread_id);
    }
  }

  return { handleChatRootPointerDown };
}
