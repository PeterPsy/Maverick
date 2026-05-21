import { Dispatch, SetStateAction, useEffect, useRef } from "react";
import type { ChatThread, RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import {
  deleteStoredRuntimeTranscript,
  readStoredRuntimeTranscript,
  type RuntimeTranscriptCacheEntry,
  writeStoredRuntimeTranscript,
} from "../lib/runtimeTranscriptCache";

type UseRuntimeTranscriptCacheParams = {
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  events: RuntimeEvent[];
  hasLoadedHistory: boolean;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setFailedUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setHasLoadedHistory: Dispatch<SetStateAction<boolean>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setQueuedMessages: Dispatch<SetStateAction<QueuedMessage[]>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

function isThreadAvailabilityBusy(availability: string) {
  return availability === "busy" || availability === "queued" || availability === "active";
}

export function useRuntimeTranscriptCache({
  activeSession,
  activeThread,
  activeTurn,
  events,
  hasLoadedHistory,
  setActiveSession,
  setActiveThread,
  setActiveTurn,
  setError,
  setEvents,
  setFailedUserMessages,
  setHasLoadedHistory,
  setPendingUserMessages,
  setQueuedMessages,
  setThreads,
}: UseRuntimeTranscriptCacheParams) {
  const activeRuntimeSessionIdRef = useRef<string | null>(null);
  const runtimeTranscriptCacheRef = useRef<Map<string, RuntimeTranscriptCacheEntry>>(new Map());

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id;
    activeRuntimeSessionIdRef.current = runtimeSessionId || null;
  }, [activeThread?.runtime_session_id]);

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id;
    if (!runtimeSessionId) {
      return;
    }
    const cacheEntry = {
      activeSession,
      activeTurn,
      events,
      hasLoadedHistory: hasLoadedHistory || events.length > 0,
    };
    runtimeTranscriptCacheRef.current.set(runtimeSessionId, cacheEntry);
    writeStoredRuntimeTranscript(runtimeSessionId, cacheEntry);
  }, [activeSession, activeThread?.runtime_session_id, activeTurn, events, hasLoadedHistory]);

  function cachedTranscriptForThread(thread: ChatThread | null) {
    if (!thread?.runtime_session_id) {
      return null;
    }
    const cachedTranscript = runtimeTranscriptCacheRef.current.get(thread.runtime_session_id);
    if (cachedTranscript) {
      return cachedTranscript;
    }
    const storedTranscript = readStoredRuntimeTranscript(thread.runtime_session_id);
    if (storedTranscript) {
      runtimeTranscriptCacheRef.current.set(thread.runtime_session_id, storedTranscript);
    }
    return storedTranscript;
  }

  function cachedActiveTurnForThread(thread: ChatThread | null, cachedTranscript: RuntimeTranscriptCacheEntry | null) {
    if (!thread || !cachedTranscript?.activeTurn || !isThreadAvailabilityBusy(thread.availability)) {
      return null;
    }
    return cachedTranscript.activeTurn;
  }

  function setActiveRuntimeSessionId(runtimeSessionId: string | null) {
    activeRuntimeSessionIdRef.current = runtimeSessionId;
  }

  async function handleUnavailableRuntimeSession(runtimeSessionId: string) {
    if (!runtimeSessionId) {
      return;
    }
    runtimeTranscriptCacheRef.current.delete(runtimeSessionId);
    deleteStoredRuntimeTranscript(runtimeSessionId);
    if (activeRuntimeSessionIdRef.current === runtimeSessionId) {
      activeRuntimeSessionIdRef.current = null;
      setActiveSession(null);
      setEvents([]);
      setHasLoadedHistory(false);
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
      setActiveTurn(null);
    }
    setThreads((current) =>
      current.map((thread) => (thread.runtime_session_id === runtimeSessionId ? { ...thread, runtime_session_id: "", availability: "free" } : thread)),
    );
    setActiveThread((current) =>
      current?.runtime_session_id === runtimeSessionId ? { ...current, runtime_session_id: "", availability: "free" } : current,
    );
    setError("This runtime session was cleaned and is no longer available.");
  }

  return {
    cachedActiveTurnForThread,
    cachedTranscriptForThread,
    handleUnavailableRuntimeSession,
    setActiveRuntimeSessionId,
  };
}
