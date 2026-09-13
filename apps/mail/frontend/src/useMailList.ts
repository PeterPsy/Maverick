import { useCallback, useEffect, useRef, useState } from 'react';
import { callBackend, MAIL_BACKEND_ACTIONS, type MailConnection, type MailThread } from './api';
import { readMailDisplay } from './pwaCache';
import { readMailThreadList } from './threadList';

type ConnectionPayload = { items: MailConnection[] };
type ThreadSnapshot = { query: string; items: MailThread[]; complete: boolean };

export function useMailList(query: string, onError: (message: string) => void) {
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [liveConnections, setLiveConnections] = useState<MailConnection[] | null>(null);
  const [snapshot, setSnapshot] = useState<ThreadSnapshot | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const { signal } = controller;
    setRefreshing(true);
    const report = (error: unknown) => {
      if (!signal.aborted) onError(error instanceof Error ? error.message : 'Unable to load mail.');
    };
    let receivedLiveConnections = false;
    const displayConnections = (next: ConnectionPayload) => {
      if (!signal.aborted && !receivedLiveConnections) setConnections((current) => next.items.map((item) => ({
        ...current.find((connection) => connection.id === item.id), ...item,
      })));
    };
    // Counts and live connection authority never gate header paint.
    void readMailDisplay<ConnectionPayload>({ kind: 'mailboxes' }, {
      signal, onRevalidated: displayConnections,
    }).then(displayConnections).catch(() => undefined);
    void callBackend<ConnectionPayload>({
      action: MAIL_BACKEND_ACTIONS.connectionsList,
      _app_secret_request: { logical_names: [], required: false },
    }).then((next) => {
      if (!signal.aborted) {
        receivedLiveConnections = true;
        setConnections(next.items);
        setLiveConnections(next.items);
      }
    }).catch(() => undefined);

    try {
      await readMailThreadList(query, signal, (items, complete) => {
        if (!signal.aborted) {
          setSnapshot((current) => current?.query === query && current.complete && !complete
            ? current : { query, items, complete });
          setRefreshing(!complete);
        }
      }, report);
    } catch (error) {
      if (!signal.aborted) {
        setSnapshot((current) => current?.query === query ? current : { query, items: [], complete: false });
        report(error);
      }
    } finally {
      if (!signal.aborted) setRefreshing(false);
    }
  }, [query, onError]);

  useEffect(() => {
    void refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  return {
    connections, liveConnections, refresh, refreshing,
    threads: snapshot?.query === query ? snapshot.items : [],
    loading: snapshot?.query !== query,
    incomplete: snapshot?.query === query && !snapshot.complete && !refreshing,
  };
}
