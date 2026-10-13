import { useCallback, useState } from "react";
import { items, operation, type Chat, type Row, type Session } from "./api";
import { useVisiblePolling } from "./useVisiblePolling";

export function useResources(session: Session | undefined, tab: string, page: number, online: boolean, revision: number) {
  const [rows, setRows] = useState<{ key: string; items: (Chat & Row)[]; error: string }>();
  const [pendingKey, setPendingKey] = useState("");
  const enabled = !!session && (session.status === "ready" || ["webhooks", "templates"].includes(tab));
  const key = JSON.stringify([session?.id, tab, page]);
  const read = useCallback(async (signal: AbortSignal) => {
    setPendingKey(key);
    try {
      const data = await operation(tab + ".list", { session_id: session?.id, limit: 50, offset: page * 50 }, signal);
      if (!signal.aborted) setRows({ key, items: items<Chat & Row>(data), error: "" });
    } catch (error) {
      if (!signal.aborted) {
        setRows((previous) => ({ key, items: previous?.key === key ? previous.items : [], error: (error as Error).message }));
        return false;
      }
    } finally {
      if (!signal.aborted) setPendingKey("");
    }
  }, [key, session?.id, tab, page, revision]);
  const refresh = useVisiblePolling(read, 10000, enabled && online);
  const current = enabled && rows?.key === key ? rows : undefined;
  return { chats: tab === "chats" ? current?.items || [] : [], records: tab !== "chats" ? current?.items || [] : [],
    loading: enabled && online && (pendingKey === key || !current), more: current?.items.length === 50,
    error: current?.error || "", refresh };
}
