import { Dispatch, SetStateAction, useEffect, useRef, useState } from "react";
import {
  AppReference,
  ChatThread,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  createThread,
  isRuntimeSessionUnavailableError,
  orderChatThreads,
} from "../api/client";
import { ActiveAppContext, loadDefaultSystemPrompt } from "../lib/activeAppContext";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { queueStorageKey, readPersistedQueuedMessages } from "../lib/queuedMessages";
import {
  deleteStoredRuntimeTranscript,
  readStoredRuntimeTranscript,
  type RuntimeTranscriptCacheEntry,
  writeStoredRuntimeTranscript,
} from "../lib/runtimeTranscriptCache";
import {
  chatNavigationRequestKey,
  consumeNewChatRequest,
  normalizeChatRouteParams,
  openChatRootRouteInShell,
  openChatThreadRouteInShell,
  runtimeSessionThreadMetadataFromParams,
  RuntimeSessionThreadMetadata,
  scalarString,
} from "../lib/shellNavigation";
import { debugThreadSync, findThreadByRuntimeSession } from "../lib/threadNavigation";
import { useRuntimeThreads } from "./useRuntimeThreads";
import type { DraftChat } from "./useMessageSubmission";

const THREAD_NOT_FOUND_MESSAGE = "This chat is no longer available.";

type CreateChatOptions = {
  activeAppContext?: ActiveAppContext | null;
  projectId?: string | null;
  resetView?: boolean;
};

type UseChatNavigationParams = {
  activeAppContext: ActiveAppContext | null;
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  clearAttachments: () => void;
  events: RuntimeEvent[];
  hasExternalRuntimeThreads: boolean;
  hasLoadedHistory: boolean;
  isBootstrapping: boolean;
  navigationScope: string;
  newChatProjectId: string | null;
  newChatRequestId: string | null;
  notifyActiveThreadChanged: (activeThreadId: string) => void;
  runtimeThreads: ChatThread[] | null;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setComposer: Dispatch<SetStateAction<string>>;
  setDraftChat: Dispatch<SetStateAction<DraftChat | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setFailedUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setHasLoadedHistory: Dispatch<SetStateAction<boolean>>;
  setIsBootstrapping: Dispatch<SetStateAction<boolean>>;
  setIsHistoryLoading: Dispatch<SetStateAction<boolean>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setQueuedMessages: Dispatch<SetStateAction<QueuedMessage[]>>;
  setSelectedReferences: Dispatch<SetStateAction<AppReference[]>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
  threadId: string | null;
  threads: ChatThread[];
};

function isThreadAvailabilityBusy(availability: string) {
  return availability === "busy" || availability === "queued" || availability === "active";
}

export function useChatNavigation({
  activeAppContext,
  activeSession,
  activeThread,
  activeTurn,
  clearAttachments,
  events,
  hasExternalRuntimeThreads,
  hasLoadedHistory,
  isBootstrapping,
  navigationScope,
  newChatProjectId,
  newChatRequestId,
  notifyActiveThreadChanged,
  runtimeThreads,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  setActiveSession,
  setActiveThread,
  setActiveTurn,
  setComposer,
  setDraftChat,
  setError,
  setEvents,
  setFailedUserMessages,
  setHasLoadedHistory,
  setIsBootstrapping,
  setIsHistoryLoading,
  setPendingUserMessages,
  setQueuedMessages,
  setSelectedReferences,
  setThreads,
  threadId,
  threads,
}: UseChatNavigationParams) {
  const [threadsLoaded, setThreadsLoaded] = useState(false);
  const consumedNewChatRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewChatRequest = useRef(false);
  const initialSelectionHandledRef = useRef(false);
  const navigationRequestRef = useRef<string | null>(null);
  const suppressedExternalThreadIdRef = useRef<string | null>(null);
  const activeRuntimeSessionIdRef = useRef<string | null>(null);
  const externalRuntimeThreadsErrorRef = useRef<string | null>(null);
  const runtimeTranscriptCacheRef = useRef<Map<string, RuntimeTranscriptCacheEntry>>(new Map());

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

  useEffect(() => {
    if (!threadsLoaded || initialSelectionHandledRef.current) {
      return;
    }
    initialSelectionHandledRef.current = true;
    void selectInitialThread();
  }, [threadsLoaded, threads]);

  useEffect(() => {
    if (isBootstrapping) {
      return;
    }
    debugThreadSync("app-thread-prop-effect", {
      activeThreadId: activeThread?.thread_id || "",
      navigationScope,
      suppressedExternalThreadId: suppressedExternalThreadIdRef.current,
      threadId,
    });
    if (!threadId || activeThread?.thread_id === threadId) {
      suppressedExternalThreadIdRef.current = null;
      return;
    }
    if (suppressedExternalThreadIdRef.current && threadId === suppressedExternalThreadIdRef.current) {
      return;
    }
    void openThreadById(threadId);
  }, [threadId, isBootstrapping, activeThread?.thread_id, threads]);

  async function selectInitialThread() {
    try {
      const query = new URLSearchParams(window.location.search);
      if (newChatRequestId) {
        suppressedExternalThreadIdRef.current = threadId || null;
        createDraftChat({ activeAppContext, projectId: newChatProjectId });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
        setError(null);
        return;
      }
      if (query.get("new_chat") === "1") {
        suppressedExternalThreadIdRef.current = threadId || null;
        createDraftChat({ activeAppContext, projectId: query.get("project_id") });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
        setError(null);
        return;
      }
      const requestedThreadId = threadId || query.get("thread_id");
      const firstThread = requestedThreadId ? threads.find((thread) => thread.thread_id === requestedThreadId) || null : threads[0] || null;
      if (!firstThread) {
        if (runtimeThreadsError) {
          setError(runtimeThreadsError);
          return;
        }
        if (requestedThreadId) {
          suppressedExternalThreadIdRef.current = requestedThreadId;
        }
        createDraftChat({ activeAppContext, resetView: false });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
        setError(requestedThreadId ? THREAD_NOT_FOUND_MESSAGE : null);
        return;
      }
      await selectThreadWithoutHttp(firstThread);
      setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, firstThread?.thread_id || null)));
      setError(null);
    } catch (selectionError) {
      setError(selectionError instanceof Error ? selectionError.message : "Unable to load chat.");
    } finally {
      setIsBootstrapping(false);
    }
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

  function resetActiveConversation() {
    setActiveThread(null);
    setDraftChat(null);
    setActiveSession(null);
    setEvents([]);
    setHasLoadedHistory(false);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    setComposer("");
    setSelectedReferences([]);
    clearAttachments();
  }

  function createDraftChat({ activeAppContext: activeAppContextOverride, projectId = null, resetView = true }: CreateChatOptions = {}) {
    initialSelectionHandledRef.current = true;
    debugThreadSync("app-create-draft-chat-start", {
      activeThreadId: activeThread?.thread_id || "",
      navigationScope,
      projectId,
      resetView,
      threadId,
    });
    if (resetView) {
      resetActiveConversation();
    }
    setActiveThread(null);
    setDraftChat({ projectId, systemPrompt: "" });
    setActiveSession(null);
    setEvents([]);
    setHasLoadedHistory(false);
    setActiveTurn(null);
    if (resetView) {
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
    }
    void loadDefaultSystemPrompt(activeAppContextOverride ?? activeAppContext).then((systemPrompt) => {
      setDraftChat((current) => (current ? { ...current, systemPrompt } : current));
    });
    openChatRootRouteInShell({ navigationScope });
  }

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

  async function selectThreadWithoutHttp(thread: ChatThread | null) {
    const cachedTranscript = cachedTranscriptForThread(thread);
    const cachedHistoryLoaded = Boolean(cachedTranscript && (cachedTranscript.hasLoadedHistory || cachedTranscript.events.length > 0));
    setIsHistoryLoading(Boolean(thread?.runtime_session_id && !cachedHistoryLoaded));
    setActiveThread(thread);
    setDraftChat(null);
    activeRuntimeSessionIdRef.current = thread?.runtime_session_id || null;
    setActiveSession(cachedTranscript?.activeSession ?? null);
    setEvents(cachedTranscript?.events ?? []);
    setHasLoadedHistory(cachedHistoryLoaded);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(cachedActiveTurnForThread(thread, cachedTranscript));
    if (!thread?.runtime_session_id) {
      setIsHistoryLoading(false);
    }
  }

  async function handleSelectThread(thread: ChatThread) {
    await selectThreadWithoutHttp(thread);
    notifyActiveThreadChanged(thread.thread_id);
    openChatThreadRouteInShell(thread.thread_id, { navigationScope });
    setError(null);
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const normalizedParams = normalizeChatRouteParams(params);
    const requestedThreadId = typeof normalizedParams.thread_id === "string" ? normalizedParams.thread_id : null;
    const requestedRuntimeSessionId = typeof normalizedParams.runtime_session_id === "string" ? normalizedParams.runtime_session_id : null;
    const newChatProjectId = scalarString(normalizedParams.project_id) || null;
    const runtimeThreadMetadata = runtimeSessionThreadMetadataFromParams(normalizedParams);
    const shouldCreateChat = normalizedParams.new_chat === true || normalizedParams.new_chat === "1";
    debugThreadSync("app-navigation", {
      activeThreadId: activeThread?.thread_id || "",
      navigationScope,
      params: normalizedParams,
      requestedRuntimeSessionId,
      requestedThreadId,
      shouldCreateChat,
      threadId,
    });
    if (!requestedThreadId && !requestedRuntimeSessionId && !shouldCreateChat) {
      return;
    }
    if (shouldCreateChat && !consumeNewChatRequest(normalizedParams, consumedNewChatRequests.current, consumedLegacyNewChatRequest)) {
      return;
    }
    const navigationRequestKey = chatNavigationRequestKey({
      newChatProjectId,
      requestedRuntimeSessionId,
      requestedThreadId,
      shouldCreateChat,
    });
    if (!shouldCreateChat) {
      if (navigationRequestRef.current === navigationRequestKey) {
        return;
      }
      if (requestedRuntimeSessionId && activeThread?.runtime_session_id === requestedRuntimeSessionId) {
        return;
      }
      if (requestedThreadId && activeThread?.thread_id === requestedThreadId) {
        return;
      }
    }
    navigationRequestRef.current = navigationRequestKey;
    setIsBootstrapping(true);
    try {
      if (requestedRuntimeSessionId) {
        await openRuntimeSessionThread(requestedRuntimeSessionId, runtimeThreadMetadata);
      } else if (shouldCreateChat) {
        suppressedExternalThreadIdRef.current = threadId || activeThread?.thread_id || null;
        debugThreadSync("app-new-chat-suppress-previous", {
          activeThreadId: activeThread?.thread_id || "",
          navigationScope,
          suppressedExternalThreadId: suppressedExternalThreadIdRef.current,
          threadId,
        });
        createDraftChat({ projectId: newChatProjectId });
      } else if (requestedThreadId) {
        suppressedExternalThreadIdRef.current = null;
        if (!(await openThreadById(requestedThreadId))) {
          return;
        }
      }
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Unable to open chat.");
    } finally {
      if (navigationRequestRef.current === navigationRequestKey) {
        navigationRequestRef.current = null;
      }
      setIsBootstrapping(false);
    }
  }

  async function openRuntimeSessionThread(runtimeSessionId: string, metadata: RuntimeSessionThreadMetadata) {
    if (activeThread?.runtime_session_id === runtimeSessionId) {
      return;
    }
    const existingThread = findThreadByRuntimeSession(threads, runtimeSessionId);
    if (existingThread) {
      if (activeThread?.thread_id === existingThread.thread_id) {
        return;
      }
      await handleSelectThread(existingThread);
      return;
    }
    setIsHistoryLoading(true);
    try {
      const payload = await createThread(runtimeSessionId, null, metadata);
      setThreads(payload.threads);
      setActiveThread(payload.thread);
      activeRuntimeSessionIdRef.current = runtimeSessionId;
      setActiveSession(null);
      setEvents([]);
      setHasLoadedHistory(false);
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
      setActiveTurn(null);
      notifyActiveThreadChanged(payload.thread.thread_id);
    } catch (runtimeSessionError) {
      if (isRuntimeSessionUnavailableError(runtimeSessionError, runtimeSessionId)) {
        await handleUnavailableRuntimeSession(runtimeSessionId);
        return;
      }
      throw runtimeSessionError;
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function openThreadById(threadId: string): Promise<boolean> {
    if (activeThread?.thread_id === threadId) {
      return true;
    }
    const existingThread = threads.find((thread) => thread.thread_id === threadId);
    if (existingThread) {
      await handleSelectThread(existingThread);
      return true;
    }
    suppressedExternalThreadIdRef.current = threadId;
    createDraftChat({ resetView: false });
    setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
    setError(THREAD_NOT_FOUND_MESSAGE);
    return false;
  }

  return {
    handleNavigationParams,
    handleSelectThread,
    handleUnavailableRuntimeSession,
  };
}
