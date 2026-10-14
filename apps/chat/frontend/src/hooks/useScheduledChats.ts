import { useCallback, useEffect, useRef, useState } from "react";
import { isExactLoopinoParentMessage } from "@loopino/pwa-cache";
import { scheduledChatAction, type ScheduledChat, type ScheduledChatSummary } from "../api/scheduledChats";

export function useScheduledChats(chatId: string | null) {
  const [chats, setChats] = useState<ScheduledChatSummary[]>([]);
  const [chat, setChat] = useState<ScheduledChat | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const refreshAbort = useRef<AbortController | null>(null);
  const mutationLock = useRef(false);

  const refresh = useCallback(async () => {
    refreshAbort.current?.abort();
    const abort = new AbortController();
    refreshAbort.current = abort;
    const version = generation.current;
    try {
      const result = await scheduledChatAction(chatId ? "read" : "list", chatId ? { chat_id: chatId } : {}, abort.signal);
      if (abort.signal.aborted || version !== generation.current) return;
      if (chatId) setChat(result.chat || null);
      else setChats(result.chats || []);
      setError(null);
    } catch (cause) {
      if (!abort.signal.aborted && version === generation.current) setError(cause instanceof Error ? cause.message : "Unable to load scheduled tasks");
    } finally {
      if (!abort.signal.aborted && version === generation.current) setLoading(false);
    }
  }, [chatId]);

  useEffect(() => {
    generation.current += 1;
    setChat(null); setChats([]); setLoading(true); setError(null);
    void refresh();
    return () => { generation.current += 1; refreshAbort.current?.abort(); };
  }, [refresh]);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (isExactLoopinoParentMessage(event) && event.data?.type === "loopino.widget.context-changed") {
        generation.current += 1; refreshAbort.current?.abort();
        setChat(null); setChats([]); setLoading(true); setError(null);
        void refresh();
        return;
      }
      if (isExactLoopinoParentMessage(event) && event.data?.type === "loopino.app.data-changed"
        && event.data.owner_app_id === "chat" && event.data.resource === "scheduled-chats") void refresh();
    }
    function onResume() { if (!document.hidden) void refresh(); }
    window.addEventListener("message", onMessage);
    document.addEventListener("visibilitychange", onResume);
    window.addEventListener("focus", onResume);
    return () => {
      window.removeEventListener("message", onMessage);
      document.removeEventListener("visibilitychange", onResume);
      window.removeEventListener("focus", onResume);
    };
  }, [refresh]);

  const active = chat ? !chat.chat_session_id || chat.message_status === "launching" || chat.message_status === "running"
    || Boolean(chat.run && !chat.run.finished_at && chat.run.steps.some(step => step.status === "running")) : false;
  useEffect(() => {
    if (!active) return;
    const interval = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    return () => window.clearInterval(interval);
  }, [active, refresh]);

  const mutate = useCallback(async (action: string, fields: Record<string, unknown> = {}) => {
    if (mutationLock.current) return null;
    const version = generation.current;
    mutationLock.current = true; setBusy(true); setError(null);
    refreshAbort.current?.abort();
    try {
      const result = await scheduledChatAction(action, { ...(chatId ? { chat_id: chatId } : {}), ...fields });
      if (version !== generation.current) return null;
      refreshAbort.current?.abort();
      if (result.chat && chatId) setChat(result.chat);
      return result;
    } catch (cause) {
      if (version === generation.current) setError(cause instanceof Error ? cause.message : "Unable to save scheduled task");
      return null;
    } finally {
      mutationLock.current = false;
      setBusy(false);
    }
  }, [chatId]);

  return { chats, chat, loading, busy, error, mutate, refresh };
}
