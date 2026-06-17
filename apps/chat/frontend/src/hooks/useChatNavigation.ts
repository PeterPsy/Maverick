import { Dispatch, SetStateAction, useEffect, useRef } from "react";
import {
  AppReference,
  ChatThread,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  createThread,
  isRuntimeSessionUnavailableError,
} from "../api/client";
import { ActiveAppContext, loadDefaultSystemPrompt } from "../lib/activeAppContext";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { queueStorageKey, readPersistedQueuedMessages } from "../lib/queuedMessages";
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
import type { DraftChat } from "./useMessageSubmission";
import { useRuntimeThreadCatalog } from "./useRuntimeThreadCatalog";
import { useRuntimeTranscriptCache } from "./useRuntimeTranscriptCache";

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
  hasMoreHistory: boolean;
  isBootstrapping: boolean;
  navigationScope: string;
  newChatProjectId: string | null;
  newChatRequestId: string | null;
  notifyActiveThreadChanged: (activeThreadId: string) => void;
  runtimeThreads: ChatThread[] | null;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  setActiveInterAgentGraphRunId: Dispatch<SetStateAction<string | null>>;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setComposer: Dispatch<SetStateAction<string>>;
  setDraftChat: Dispatch<SetStateAction<DraftChat | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setFailedUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setHasLoadedHistory: Dispatch<SetStateAction<boolean>>;
  setHasMoreHistory: Dispatch<SetStateAction<boolean>>;
  setIsOlderHistoryLoading: Dispatch<SetStateAction<boolean>>;
  setIsBootstrapping: Dispatch<SetStateAction<boolean>>;
  setIsHistoryLoading: Dispatch<SetStateAction<boolean>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
  setQueuedMessages: Dispatch<SetStateAction<QueuedMessage[]>>;
  setSelectedReferences: Dispatch<SetStateAction<AppReference[]>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
  threadId: string | null;
  threads: ChatThread[];
};

export function useChatNavigation({
  activeAppContext,
  activeSession,
  activeThread,
  activeTurn,
  clearAttachments,
  events,
  hasExternalRuntimeThreads,
  hasLoadedHistory,
  hasMoreHistory,
  isBootstrapping,
  navigationScope,
  newChatProjectId,
  newChatRequestId,
  notifyActiveThreadChanged,
  runtimeThreads,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  setActiveInterAgentGraphRunId,
  setActiveSession,
  setActiveThread,
  setActiveTurn,
  setComposer,
  setDraftChat,
  setError,
  setEvents,
  setFailedUserMessages,
  setHasLoadedHistory,
  setHasMoreHistory,
  setIsBootstrapping,
  setIsHistoryLoading,
  setIsOlderHistoryLoading,
  setPendingUserMessages,
  setQueuedMessages,
  setSelectedReferences,
  setThreads,
  threadId,
  threads,
}: UseChatNavigationParams) {
  const consumedNewChatRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewChatRequest = useRef(false);
  const handledNewChatPropRequestRef = useRef<string | null>(null);
  const initialSelectionHandledRef = useRef(false);
  const navigationRequestRef = useRef<string | null>(null);
  const suppressedExternalThreadIdRef = useRef<string | null>(null);

  const { threadsLoaded } = useRuntimeThreadCatalog({
    hasExternalRuntimeThreads,
    runtimeThreads,
    runtimeThreadsError,
    runtimeThreadsLoaded,
    setActiveThread,
    setError,
    setThreads,
    threads,
  });

  const { cachedActiveTurnForThread, cachedTranscriptForThread, handleUnavailableRuntimeSession, setActiveRuntimeSessionId } =
    useRuntimeTranscriptCache({
      activeSession,
      activeThread,
      activeTurn,
      events,
      hasLoadedHistory,
      hasMoreHistory,
      setActiveSession,
      setActiveThread,
      setActiveTurn,
      setError,
      setEvents,
      setFailedUserMessages,
      setHasLoadedHistory,
      setHasMoreHistory,
      setPendingUserMessages,
      setQueuedMessages,
      setThreads,
    });

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

  useEffect(() => {
    if (!threadsLoaded || isBootstrapping || !newChatRequestId || handledNewChatPropRequestRef.current === newChatRequestId) {
      return;
    }
    handledNewChatPropRequestRef.current = newChatRequestId;
    void handleNavigationParams({
      new_chat: "1",
      new_chat_request_id: newChatRequestId,
      project_id: newChatProjectId || null,
    });
  }, [threadsLoaded, isBootstrapping, newChatProjectId, newChatRequestId]);

  async function selectInitialThread() {
    try {
      const query = new URLSearchParams(window.location.search);
      if (newChatRequestId) {
        handledNewChatPropRequestRef.current = newChatRequestId;
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
      const requestedGraphRunId = query.get("view") === "graph" ? query.get("inter_agent_run_id") || "" : "";
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
      setActiveInterAgentGraphRunId(requestedGraphRunId || null);
      setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, firstThread?.thread_id || null)));
      setError(null);
    } catch (selectionError) {
      setError(selectionError instanceof Error ? selectionError.message : "Unable to load chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  function resetActiveConversation() {
    setActiveThread(null);
    setDraftChat(null);
    setActiveSession(null);
    setEvents([]);
    setHasLoadedHistory(false);
    setHasMoreHistory(false);
    setIsHistoryLoading(false);
    setIsOlderHistoryLoading(false);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    setActiveInterAgentGraphRunId(null);
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
    setActiveInterAgentGraphRunId(null);
    setActiveSession(null);
    setEvents([]);
    setHasLoadedHistory(false);
    setHasMoreHistory(false);
    setIsHistoryLoading(false);
    setIsOlderHistoryLoading(false);
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

  async function selectThreadWithoutHttp(thread: ChatThread | null) {
    const cachedTranscript = cachedTranscriptForThread(thread);
    const cachedHistoryLoaded = Boolean(cachedTranscript && (cachedTranscript.hasLoadedHistory || cachedTranscript.events.length > 0));
    setIsHistoryLoading(Boolean(thread?.runtime_session_id && !cachedHistoryLoaded));
    setActiveThread(thread);
    setDraftChat(null);
    setActiveRuntimeSessionId(thread?.runtime_session_id || null);
    setActiveSession(cachedTranscript?.activeSession ?? null);
    setEvents(cachedTranscript?.events ?? []);
    setHasLoadedHistory(cachedHistoryLoaded);
    setHasMoreHistory(cachedTranscript?.hasMoreHistory === true);
    setIsOlderHistoryLoading(false);
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
    setActiveInterAgentGraphRunId(null);
    notifyActiveThreadChanged(thread.thread_id);
    openChatThreadRouteInShell(thread.thread_id, { navigationScope });
    setError(null);
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const normalizedParams = normalizeChatRouteParams(params);
    const requestedThreadId = typeof normalizedParams.thread_id === "string" ? normalizedParams.thread_id : null;
    const requestedRuntimeSessionId = typeof normalizedParams.runtime_session_id === "string" ? normalizedParams.runtime_session_id : null;
    const requestedGraphRunId = scalarString(normalizedParams.view) === "graph" ? scalarString(normalizedParams.inter_agent_run_id) : "";
    const newChatProjectId = scalarString(normalizedParams.project_id) || null;
    const runtimeThreadMetadata = runtimeSessionThreadMetadataFromParams(normalizedParams);
    const shouldCreateChat = normalizedParams.new_chat === true || normalizedParams.new_chat === "1";
    debugThreadSync("app-navigation", {
      activeThreadId: activeThread?.thread_id || "",
      navigationScope,
      params: normalizedParams,
      requestedRuntimeSessionId,
      requestedThreadId,
      requestedGraphRunId,
      shouldCreateChat,
      threadId,
    });
    if (!requestedThreadId && !requestedRuntimeSessionId && !shouldCreateChat && !requestedGraphRunId) {
      return;
    }
    if (!requestedThreadId && !requestedRuntimeSessionId && !shouldCreateChat && requestedGraphRunId) {
      setActiveInterAgentGraphRunId(requestedGraphRunId);
      return;
    }
    if (shouldCreateChat && !consumeNewChatRequest(normalizedParams, consumedNewChatRequests.current, consumedLegacyNewChatRequest)) {
      return;
    }
    const navigationRequestKey = `${chatNavigationRequestKey({
      newChatProjectId,
      requestedRuntimeSessionId,
      requestedThreadId,
      shouldCreateChat,
    })}:${requestedGraphRunId}`;
    if (!shouldCreateChat) {
      if (navigationRequestRef.current === navigationRequestKey) {
        return;
      }
      if (!requestedGraphRunId && requestedRuntimeSessionId && activeThread?.runtime_session_id === requestedRuntimeSessionId) {
        return;
      }
      if (!requestedGraphRunId && requestedThreadId && activeThread?.thread_id === requestedThreadId) {
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
      setActiveInterAgentGraphRunId(requestedGraphRunId || null);
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
      setActiveRuntimeSessionId(runtimeSessionId);
      setActiveSession(null);
      setEvents([]);
      setHasLoadedHistory(false);
      setHasMoreHistory(false);
      setIsOlderHistoryLoading(false);
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
