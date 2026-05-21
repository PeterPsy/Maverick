import { Dispatch, SetStateAction, useEffect, useRef, useState } from "react";
import { ChatThread, orderChatThreads } from "../api/client";
import { useRuntimeThreads } from "./useRuntimeThreads";

type UseRuntimeThreadCatalogParams = {
  hasExternalRuntimeThreads: boolean;
  runtimeThreads: ChatThread[] | null;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
  threads: ChatThread[];
};

export function useRuntimeThreadCatalog({
  hasExternalRuntimeThreads,
  runtimeThreads,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  setActiveThread,
  setError,
  setThreads,
  threads,
}: UseRuntimeThreadCatalogParams) {
  const [threadsLoaded, setThreadsLoaded] = useState(false);
  const externalRuntimeThreadsErrorRef = useRef<string | null>(null);

  useRuntimeThreads({
    enabled: !hasExternalRuntimeThreads,
    onSnapshot: () => setThreadsLoaded(true),
    setError,
    setThreads,
  });

  useEffect(() => {
    if (!hasExternalRuntimeThreads) {
      return;
    }
    if (runtimeThreadsError) {
      externalRuntimeThreadsErrorRef.current = runtimeThreadsError;
      setError(runtimeThreadsError);
      return;
    }
    if (externalRuntimeThreadsErrorRef.current) {
      const previousRuntimeThreadsError = externalRuntimeThreadsErrorRef.current;
      externalRuntimeThreadsErrorRef.current = null;
      setError((current) => (current === previousRuntimeThreadsError ? null : current));
    }
    setThreads(orderChatThreads(runtimeThreads || []));
    if (runtimeThreadsLoaded) {
      setThreadsLoaded(true);
    }
  }, [hasExternalRuntimeThreads, runtimeThreads, runtimeThreadsError, runtimeThreadsLoaded, setError, setThreads]);

  useEffect(() => {
    setActiveThread((current) => {
      if (!current) {
        return current;
      }
      return threads.find((thread) => thread.thread_id === current.thread_id) || current;
    });
  }, [setActiveThread, threads]);

  return { threadsLoaded };
}
