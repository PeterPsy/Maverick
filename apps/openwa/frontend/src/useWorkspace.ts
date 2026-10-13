import { useCallback, useRef, useState } from "react";
import { callBackend, items, operation, type Session, type Status } from "./api";
import { useVisiblePolling } from "./useVisiblePolling";

export function useWorkspace() {
  const [status, setStatus] = useState<Status>();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [online, setOnline] = useState<boolean>();
  const scope = useRef("");
  const read = useCallback(async (signal: AbortSignal) => {
    setRefreshing(true);
    try {
      const next = await callBackend<Status>({ action: "status" }, signal);
      if (signal.aborted) return;
      if (scope.current !== next.send_scope || !next.connection.configured || !next.connection.credential_available) {
        scope.current = next.send_scope;
        setSessions([]);
        setSelected("");
        setOnline(undefined);
      }
      setStatus(next);
      if (next.connection.configured && next.connection.credential_available) {
        const rows = items<Session>(await operation("sessions.list", {}, signal));
        if (signal.aborted) return;
        setSessions(rows);
        setOnline(true);
        setSelected((previous) => rows.some((row) => row.id === previous) ? previous : rows[0]?.id || "");
      }
      setError("");
    } catch (error) {
      if (!signal.aborted) {
        setOnline(false);
        setError((error as Error).message);
        return false;
      }
    } finally {
      if (!signal.aborted) { setLoading(false); setRefreshing(false); }
    }
  }, []);
  const refresh = useVisiblePolling(read, 10000);
  return { status, sessions, selected, setSelected, error, loading, refreshing, online, refresh };
}
