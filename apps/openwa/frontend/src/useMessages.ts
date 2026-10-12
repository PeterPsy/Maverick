import { useCallback, useState } from "react";
import { items, operation, type Message } from "./api";
import { useVisiblePolling } from "./useVisiblePolling";

export function useMessages(sessionId: string, chatId: string, page: number, enabled: boolean) {
  const key = JSON.stringify([sessionId, chatId, page]);
  const [snapshot, setSnapshot] = useState<{ key: string; rows: Message[]; error: string }>();
  const [pendingKey, setPendingKey] = useState("");
  const read = useCallback(async (signal: AbortSignal) => {
    setPendingKey(key);
    try {
      const data = await operation("messages.list", {
        session_id: sessionId, chat_id: chatId, limit: 50, offset: page * 50,
      }, signal);
      if (!signal.aborted) setSnapshot({ key, rows: items<Message>(data).slice().reverse(), error: "" });
    } catch (error) {
      if (!signal.aborted) {
        setSnapshot((previous) => ({ key, rows: previous?.key === key ? previous.rows : [], error: (error as Error).message }));
        return false;
      }
    } finally {
      if (!signal.aborted) setPendingKey("");
    }
  }, [key, sessionId, chatId, page]);
  const refresh = useVisiblePolling(read, 8000, enabled);
  const current = snapshot?.key === key ? snapshot : undefined;
  return { rows: current?.rows || [], error: current?.error || "", more: current?.rows.length === 50,
    loading: enabled && (pendingKey === key || !current), refresh };
}
