import { Dispatch, SetStateAction, useEffect, useRef } from "react";
import type { ChatThread, RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { clearTranscriptProjectionCache } from '../lib/transcript';
import {
  RuntimeTranscriptCache,
  type RuntimeTranscriptCacheEntry,
} from "../lib/runtimeTranscriptCache";

type UseRuntimeTranscriptCacheParams = {
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  events: RuntimeEvent[];
  hasLoadedHistory: boolean;
  hasMoreHistory: boolean;
  hasNewerHistory?: boolean;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setFailedUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setHasLoadedHistory: Dispatch<SetStateAction<boolean>>;
  setHasMoreHistory: Dispatch<SetStateAction<boolean>>;
  setHasNewerHistory?: Dispatch<SetStateAction<boolean>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setQueuedMessages: Dispatch<SetStateAction<QueuedMessage[]>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

function isThreadAvailabilityBusy(availability: string) {
  return availability === "busy" || availability === "queued" || availability === "active";
}

export function isRuntimeTurnBusy(turn: Pick<RuntimeTurn, "status"> | null | undefined) {
  return turn?.status === "queued" || turn?.status === "active" || turn?.status === "waiting_for_tool_confirmation";
}

export function selectCachedActiveTurnForThread(thread: ChatThread | null, cachedTranscript: RuntimeTranscriptCacheEntry | null) {
  if (!thread || !cachedTranscript?.activeTurn || !isThreadAvailabilityBusy(thread.availability) || !isRuntimeTurnBusy(cachedTranscript.activeTurn)) {
    return null;
  }
  return cachedTranscript.activeTurn;
}

export function useRuntimeTranscriptCache({
  activeSession,
  activeThread,
  activeTurn,
  events,
  hasLoadedHistory,
  hasMoreHistory,
  hasNewerHistory,
  setActiveSession,
  setActiveThread,
  setActiveTurn,
  setError,
  setEvents,
  setFailedUserMessages,
  setHasLoadedHistory,
  setHasMoreHistory,
  setHasNewerHistory,
  setPendingUserMessages,
  setQueuedMessages,
  setThreads,
}: UseRuntimeTranscriptCacheParams) {
  const activeRuntimeSessionIdRef = useRef<string | null>(null);
  const runtimeTranscriptCacheRef = useRef(new RuntimeTranscriptCache());
  const activeEntryRef = useRef<{ id: string; entry: RuntimeTranscriptCacheEntry } | null>(null);

  useEffect(() => {
    const clear = () => {
      runtimeTranscriptCacheRef.current.clear();
      activeEntryRef.current = null;
      clearTranscriptProjectionCache();
    };
    window.addEventListener('pagehide', clear);
    return () => { window.removeEventListener('pagehide', clear); clear(); };
  }, []);

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id;
    activeRuntimeSessionIdRef.current = runtimeSessionId || null;
  }, [activeThread?.runtime_session_id]);

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id;
    const previous = activeEntryRef.current;
    if (previous && previous.id !== runtimeSessionId) {
      runtimeTranscriptCacheRef.current.set(previous.id, previous.entry);
      activeEntryRef.current = null;
    }
    if (!runtimeSessionId) {
      return;
    }
    const previousEntry = activeEntryRef.current?.entry ?? runtimeTranscriptCacheRef.current.get(runtimeSessionId);
    const cacheEntry = {
      activeSession: activeSession ?? previousEntry?.activeSession ?? null,
      activeTurn,
      events,
      hasLoadedHistory,
      hasMoreHistory,
      hasNewerHistory,
    };
    runtimeTranscriptCacheRef.current.delete(runtimeSessionId);
    activeEntryRef.current = { id: runtimeSessionId, entry: cacheEntry };
  }, [activeSession, activeThread?.runtime_session_id, activeTurn, events, hasLoadedHistory, hasMoreHistory, hasNewerHistory]);

  function cachedTranscriptForThread(thread: ChatThread | null) {
    if (!thread?.runtime_session_id) {
      return null;
    }
    if (activeEntryRef.current?.id === thread.runtime_session_id) return activeEntryRef.current.entry;
    const cachedTranscript = runtimeTranscriptCacheRef.current.get(thread.runtime_session_id);
    if (cachedTranscript) {
      return cachedTranscript;
    }
    return null;
  }

  function cachedActiveTurnForThread(thread: ChatThread | null, cachedTranscript: RuntimeTranscriptCacheEntry | null) {
    return selectCachedActiveTurnForThread(thread, cachedTranscript);
  }

  function setActiveRuntimeSessionId(runtimeSessionId: string | null) {
    activeRuntimeSessionIdRef.current = runtimeSessionId;
  }

  async function handleUnavailableRuntimeSession(runtimeSessionId: string) {
    if (!runtimeSessionId) {
      return;
    }
    runtimeTranscriptCacheRef.current.delete(runtimeSessionId);
    if (activeEntryRef.current?.id === runtimeSessionId) activeEntryRef.current = null;
    if (activeRuntimeSessionIdRef.current === runtimeSessionId) {
      activeRuntimeSessionIdRef.current = null;
      setActiveSession(null);
      setEvents([]);
      setHasLoadedHistory(false);
      setHasMoreHistory(false);
      setHasNewerHistory?.(false);
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
