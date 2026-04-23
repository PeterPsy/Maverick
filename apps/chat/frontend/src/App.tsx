import { type MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import {
  ChatMessageAttachment,
  ChatThread,
  createRuntimeSession,
  createThread,
  AppReference,
  getAgentsCommonPrompt,
  getThread,
  getRuntimeSession,
  getWidgetContext,
  interruptRuntimeTurn,
  listApps,
  listProviders,
  listRuntimeEvents,
  listSkills,
  listThreads,
  ProviderItem,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  selectProvider,
  sendRuntimeTurn,
  updateThread,
} from "./api/client";
import { ChatComposer } from "./components/ChatComposer";
import { ChatHeader } from "./components/ChatHeader";
import { ChatTranscript } from "./components/ChatTranscript";
import { useComposerAttachments } from "./hooks/useComposerAttachments";
import { useRuntimeEvents } from "./hooks/useRuntimeEvents";
import { hasInvalidAttachments } from "./lib/attachments";
import { appReferencesFromText } from "./lib/mentions";
import type { MentionItem } from "./lib/mentions";
import { PendingMessage, QueuedMessage, uploadComposerAttachment } from "./lib/messageState";
import { inferActiveRuntimeTurn, mergeRuntimeEvents } from "./lib/runtimeEvents";
import { latestRuntimeStepLabel } from "./lib/runtimeStepLabels";
import { findThreadByRuntimeSession } from "./lib/threadNavigation";
import { eventsToMessages, firstUserTitle } from "./lib/transcript";

type ShellNavigationMessage = {
  type?: string;
  context?: Record<string, unknown>;
  deleted_thread_id?: string;
  error?: string;
  files?: unknown[];
  navigation_scope?: string;
  owner_app_id?: string;
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
};

type RuntimeSessionThreadMetadata = {
  agent_label?: string;
  agent_type_id?: string;
  agent_role_id?: string;
  source_app_id?: string;
  title?: string;
};

type CreateChatOptions = {
  activeAppContext?: ActiveAppContext | null;
  projectId?: string | null;
  resetView?: boolean;
};

type ActiveAppContext = {
  app_id: string;
  description: string;
  name: string;
  views: string[];
};

type RuntimeHistoryCacheEntry = {
  activeTurn: RuntimeTurn | null;
  events: RuntimeEvent[];
  session: RuntimeSession | null;
};

const MESSAGE_HISTORY_LIMIT = 50;
const RUNTIME_EVENT_REPLAY_LIMIT = 1000;
const QUEUED_MESSAGES_STORAGE_PREFIX = "maverick.chat.queued-messages.v1";
const RUNTIME_HISTORY_CACHE_STORAGE_PREFIX = "maverick.chat.runtime-history-cache.v1";
const RUNTIME_HISTORY_CACHE_EVENT_LIMIT = 350;
const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";

export function App({
  enablePageCapture = false,
  navigationScope = "",
  threadId = null,
}: {
  enablePageCapture?: boolean;
  navigationScope?: string;
  threadId?: string | null;
} = {}) {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [activeProviderId, setActiveProviderId] = useState("codex");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [composer, setComposer] = useState("");
  const { addAttachments, attachments, clearAttachments, removeAttachment } = useComposerAttachments();
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingMessage[]>([]);
  const [failedUserMessages, setFailedUserMessages] = useState<PendingMessage[]>([]);
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [activeAppContext, setActiveAppContext] = useState<ActiveAppContext | null>(null);
  const consumedNewChatRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewChatRequest = useRef(false);
  const historyCacheRef = useRef<Map<string, RuntimeHistoryCacheEntry>>(new Map());
  const lastPublishedRuntimeBusyState = useRef<string | null>(null);
  const historyRequestIdRef = useRef(0);
  const hasHydratedQueuedMessagesRef = useRef(false);
  const suppressedExternalThreadIdRef = useRef<string | null>(null);
  const activeRuntimeSessionIdRef = useRef<string | null>(null);

  const messages = useMemo(() => {
    const currentMessages = eventsToMessages(events);
    const confirmedHumanMessages = new Set(currentMessages.filter((message) => message.role === "human").map((message) => message.content.trim()));
    const visibleMessages = [
      ...currentMessages,
      ...pendingUserMessages
        .filter((message) => !confirmedHumanMessages.has(message.content.trim()))
        .map((message) => ({
          id: message.clientMessageId,
          role: "human" as const,
          content: message.content,
          createdAt: message.createdAt,
          status: "pending" as const,
          attachments: message.attachments,
          appReferences: message.appReferences,
        })),
      ...failedUserMessages.map((message) => ({
        id: `${message.clientMessageId}:failed`,
        role: "human" as const,
        content: message.content,
        createdAt: message.createdAt,
        status: "failed" as const,
        attachments: message.attachments,
        appReferences: message.appReferences,
      })),
    ];
    return visibleMessages.slice(-MESSAGE_HISTORY_LIMIT);
  }, [events, failedUserMessages, pendingUserMessages]);
  const executionMode = activeSession?.effective_mode || "runtime";
  const canStopTurn = activeTurn?.status === "queued" || activeTurn?.status === "active";
  const isRuntimeBusy = canStopTurn;
  const loadingLabel = useMemo(() => {
    if (isHistoryLoading) {
      return "Loading history";
    }
    if (isBootstrapping) {
      return "Loading chat";
    }
    if (!isRuntimeBusy) {
      return "";
    }
    return latestRuntimeStepLabel(events, activeTurn?.turn_id) || "Thinking";
  }, [activeTurn?.turn_id, events, isBootstrapping, isHistoryLoading, isRuntimeBusy]);

  useRuntimeEvents({
    activeTurn,
    runtimeSessionId: activeThread?.runtime_session_id || null,
    setActiveTurn,
    setError,
    setEvents,
    setPendingUserMessages,
  });

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id;
    activeRuntimeSessionIdRef.current = runtimeSessionId || null;
    if (!runtimeSessionId) {
      return;
    }
    const cacheEntry = {
      activeTurn,
      events,
      session: activeSession,
    };
    historyCacheRef.current.set(runtimeSessionId, cacheEntry);
    persistRuntimeHistoryCache(runtimeHistoryCacheKey(navigationScope, runtimeSessionId), cacheEntry);
  }, [activeSession, activeThread?.runtime_session_id, activeTurn, events]);

  useEffect(() => {
    if (!activeThread) {
      lastPublishedRuntimeBusyState.current = null;
      return;
    }
    if (navigationScope && threadId && activeThread.thread_id !== threadId) {
      debugThreadSync("app-skip-stale-thread-publication", {
        activeThreadId: activeThread.thread_id,
        navigationScope,
        threadId,
      });
      return;
    }
    const publicationKey = `${activeThread.thread_id}:${isRuntimeBusy ? "busy" : "free"}`;
    if (lastPublishedRuntimeBusyState.current === publicationKey) {
      return;
    }
    lastPublishedRuntimeBusyState.current = publicationKey;
    notifyChatThreadsChanged({ active_thread_id: activeThread.thread_id });
  }, [activeThread?.thread_id, isRuntimeBusy]);

  async function loadInitialState() {
    setIsBootstrapping(true);
    try {
      const widgetActiveAppContext = await loadWidgetActiveAppContext();
      setActiveAppContext(widgetActiveAppContext);
      const [providerPayload, threadPayload] = await Promise.all([listProviders(), listThreads()]);
      setProviders(providerPayload.items || [providerPayload.active_provider]);
      setActiveProviderId(providerPayload.active_provider.provider_id);
      setThreads(threadPayload.threads);
      const query = new URLSearchParams(window.location.search);
      const requestedThreadId = threadId || query.get("thread_id");
      if (query.get("new_chat") === "1") {
        const firstThread = await createChat({ activeAppContext: widgetActiveAppContext, projectId: query.get("project_id") });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, firstThread?.thread_id || null)));
        setError(null);
        return;
      }
      let firstThread = requestedThreadId ? threadPayload.threads.find((thread) => thread.thread_id === requestedThreadId) || null : threadPayload.threads[0] || null;
      if (requestedThreadId && !firstThread) {
        const thread = await getThread(requestedThreadId);
        firstThread = thread.thread;
        setThreads(thread.threads);
      }
      setActiveThread(firstThread);
      if (firstThread?.runtime_session_id) {
        activeRuntimeSessionIdRef.current = firstThread.runtime_session_id;
        const cachedHistory = readRuntimeHistoryCache(runtimeHistoryCacheKey(navigationScope, firstThread.runtime_session_id));
        if (cachedHistory) {
          historyCacheRef.current.set(firstThread.runtime_session_id, cachedHistory);
          setActiveSession(cachedHistory.session);
          setEvents(cachedHistory.events);
          setActiveTurn(cachedHistory.activeTurn || inferActiveRuntimeTurn(cachedHistory.events, firstThread.runtime_session_id));
          void refreshRuntimeHistory(firstThread.runtime_session_id);
        } else {
          const runtimeHistory = await fetchRuntimeHistory(firstThread.runtime_session_id);
          setActiveSession(runtimeHistory.session);
          setEvents(runtimeHistory.events);
          setActiveTurn(runtimeHistory.activeTurn);
        }
      } else {
        setActiveSession(null);
        setActiveTurn(null);
      }
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, firstThread?.thread_id || null)));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  useEffect(() => {
    loadInitialState();
    void loadMentionItems();
  }, []);

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
  }, [threadId, isBootstrapping, activeThread?.thread_id]);

  async function loadMentionItems() {
    const [appsResult, skillsResult] = await Promise.allSettled([listApps(), listSkills()]);
    const appMentions =
      appsResult.status === "fulfilled"
        ? appsResult.value.map((app) => ({
            id: app.app_id,
            label: app.name,
            description: app.description,
            kind: "app" as const,
          }))
        : [];
    const skillMentions =
      skillsResult.status === "fulfilled"
        ? skillsResult.value.map((skill) => ({
            id: skill.id,
            label: skill.name,
            description: skill.description,
            kind: "skill" as const,
          }))
        : [];
    setMentionItems([...appMentions, ...skillMentions]);
  }

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as ShellNavigationMessage;
      if (payload.type === "maverick.widget.capture-area.complete") {
        if (navigationScope && payload.navigation_scope !== navigationScope) {
          return;
        }
        const files = Array.isArray(payload.files) ? payload.files.filter((file): file is File => file instanceof File) : [];
        if (files.length) {
          addAttachments(files);
          setComposerError(null);
        }
        return;
      }
      if (payload.type === "maverick.widget.capture-area.error") {
        if (navigationScope && payload.navigation_scope !== navigationScope) {
          return;
        }
        setComposerError(payload.error || "Unable to capture page area.");
        return;
      }
      if (payload.type === "maverick.widget.context-changed") {
        setActiveAppContext(activeAppContextFromWidgetContext(payload.context || {}));
        return;
      }
      if (navigationScope && payload.navigation_scope !== navigationScope) {
        return;
      }
      if (!navigationScope && payload.navigation_scope) {
        return;
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === "chat" && payload.resource === "threads") {
        void refreshThreadsAfterDataChange(payload.deleted_thread_id || "");
        return;
      }
      if (payload.type !== "maverick.app.navigate" || (payload.app_id && payload.app_id !== "chat")) {
        return;
      }
      void handleNavigationParams(payload.params || {});
    }

    window.addEventListener("message", handleShellMessage);
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "chat" }, window.location.origin);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [activeThread?.thread_id, threads]);

  async function refreshThreadsAfterDataChange(deletedThreadId: string) {
    try {
      const payload = await listThreads();
      setThreads(payload.threads);
      const activeThreadStillExists = activeThread ? payload.threads.some((thread) => thread.thread_id === activeThread.thread_id) : false;
      if (activeThread && (!activeThreadStillExists || activeThread.thread_id === deletedThreadId)) {
        setActiveThread(null);
        setActiveSession(null);
        setEvents([]);
        setPendingUserMessages([]);
        setFailedUserMessages([]);
        setQueuedMessages([]);
        setActiveTurn(null);
      }
      setError(null);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Unable to refresh chats.");
    }
  }

  async function handleSelectProvider(providerId: string) {
    setActiveProviderId(providerId);
    try {
      const payload = await selectProvider(providerId);
      setActiveProviderId(payload.active_provider.provider_id);
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to select provider.");
    }
  }

  function resetActiveConversation() {
    setActiveThread(null);
    setActiveSession(null);
    setEvents([]);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    setComposer("");
    clearAttachments();
  }

  async function createChat({ activeAppContext: activeAppContextOverride, projectId = null, resetView = true }: CreateChatOptions = {}) {
    debugThreadSync("app-create-chat-start", {
      activeThreadId: activeThread?.thread_id || "",
      navigationScope,
      projectId,
      resetView,
      threadId,
    });
    if (resetView) {
      resetActiveConversation();
    }
    const systemPrompt = await loadDefaultSystemPrompt(activeAppContextOverride ?? activeAppContext);
    const payload = await createThread("", projectId, { system_prompt: systemPrompt });
    setThreads(payload.threads);
    setActiveThread(payload.thread);
    setActiveSession(null);
    setEvents([]);
    if (resetView) {
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
    }
    setActiveTurn(null);
    debugThreadSync("app-create-chat-complete", {
      createdThreadId: payload.thread.thread_id,
      navigationScope,
      threadId,
    });
    notifyChatThreadsChanged({ active_thread_id: payload.thread.thread_id });
    return payload.thread;
  }

  async function handleSelectThread(thread: ChatThread) {
    const requestId = historyRequestIdRef.current + 1;
    historyRequestIdRef.current = requestId;
    const cachedHistory = thread.runtime_session_id ? historyCacheRef.current.get(thread.runtime_session_id) || readRuntimeHistoryCache(runtimeHistoryCacheKey(navigationScope, thread.runtime_session_id)) : null;
    setIsHistoryLoading(!cachedHistory);
    setActiveThread(thread);
    activeRuntimeSessionIdRef.current = thread.runtime_session_id || null;
    setActiveSession(cachedHistory?.session || null);
    setEvents(cachedHistory?.events || []);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(cachedHistory?.activeTurn || (cachedHistory && thread.runtime_session_id ? inferActiveRuntimeTurn(cachedHistory.events, thread.runtime_session_id) : null));
    try {
      if (!thread.runtime_session_id) {
        setError(null);
        return;
      }
      const runtimeHistory = await fetchRuntimeHistory(thread.runtime_session_id);
      if (historyRequestIdRef.current !== requestId) {
        return;
      }
      setActiveSession(runtimeHistory.session);
      setEvents(runtimeHistory.events);
      setActiveTurn(runtimeHistory.activeTurn);
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to load thread.");
    } finally {
      if (historyRequestIdRef.current === requestId) {
        setIsHistoryLoading(false);
      }
    }
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedThreadId = typeof params.thread_id === "string" ? params.thread_id : null;
    const requestedRuntimeSessionId = typeof params.runtime_session_id === "string" ? params.runtime_session_id : null;
    const newChatProjectId = scalarString(params.project_id) || null;
    const runtimeThreadMetadata = runtimeSessionThreadMetadataFromParams(params);
    const shouldCreateChat = params.new_chat === true || params.new_chat === "1";
    debugThreadSync("app-navigation", {
      activeThreadId: activeThread?.thread_id || "",
      navigationScope,
      params,
      requestedRuntimeSessionId,
      requestedThreadId,
      shouldCreateChat,
      threadId,
    });
    if (!requestedThreadId && !requestedRuntimeSessionId && !shouldCreateChat) {
      return;
    }
    if (shouldCreateChat && !consumeNewChatRequest(params, consumedNewChatRequests.current, consumedLegacyNewChatRequest)) {
      return;
    }
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
        await createChat({ projectId: newChatProjectId });
      } else if (requestedThreadId) {
        suppressedExternalThreadIdRef.current = null;
        await openThreadById(requestedThreadId);
      }
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Unable to open chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  async function openRuntimeSessionThread(runtimeSessionId: string, metadata: RuntimeSessionThreadMetadata) {
    const existingThread = findThreadByRuntimeSession(threads, runtimeSessionId);
    if (existingThread) {
      await handleSelectThread(existingThread);
      return;
    }
    setIsHistoryLoading(true);
    try {
      const [runtimeSession, payload] = await Promise.all([getRuntimeSession(runtimeSessionId), createThread(runtimeSessionId, null, metadata)]);
      setThreads(payload.threads);
      setActiveThread(payload.thread);
      activeRuntimeSessionIdRef.current = runtimeSessionId;
      setActiveSession(runtimeSession);
      const runtimeHistory = await fetchRuntimeHistory(runtimeSessionId);
      setActiveSession(runtimeHistory.session);
      setEvents(runtimeHistory.events);
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
      setActiveTurn(runtimeHistory.activeTurn);
      notifyChatThreadsChanged({ active_thread_id: payload.thread.thread_id });
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function openThreadById(threadId: string) {
    if (activeThread?.thread_id === threadId && (!activeThread.runtime_session_id || activeSession || events.length > 0)) {
      return;
    }
    const existingThread = threads.find((thread) => thread.thread_id === threadId);
    if (existingThread) {
      await handleSelectThread(existingThread);
      return;
    }
    const payload = await getThread(threadId);
    setThreads(payload.threads);
    await handleSelectThread(payload.thread);
  }

  function notifyChatThreadsChanged(detail: Record<string, string> = {}) {
    debugThreadSync("app-notify-threads", {
      activeThreadId: activeThread?.thread_id || "",
      detail,
      navigationScope,
      threadId,
    });
    notifyAppDataChanged("chat", "threads", { ...(navigationScope ? { navigation_scope: navigationScope } : {}), ...detail });
  }

  async function fetchRuntimeHistory(runtimeSessionId: string): Promise<RuntimeHistoryCacheEntry> {
    const [runtimeSession, runtimeEvents] = await Promise.all([
      getRuntimeSession(runtimeSessionId),
      listRuntimeEvents(runtimeSessionId, { limit: RUNTIME_EVENT_REPLAY_LIMIT }),
    ]);
    return {
      activeTurn: inferActiveRuntimeTurn(runtimeEvents.items, runtimeSessionId),
      events: runtimeEvents.items,
      session: runtimeSession,
    };
  }

  async function refreshRuntimeHistory(runtimeSessionId: string) {
    try {
      const runtimeHistory = await fetchRuntimeHistory(runtimeSessionId);
      if (activeRuntimeSessionIdRef.current !== runtimeSessionId) {
        return;
      }
      setActiveSession(runtimeHistory.session);
      setEvents(runtimeHistory.events);
      setActiveTurn(runtimeHistory.activeTurn);
      setError(null);
    } catch (historyError) {
      if (events.length === 0) {
        setError(historyError instanceof Error ? historyError.message : "Unable to refresh runtime history.");
      }
    }
  }

  useEffect(() => {
    if (isBootstrapping) {
      return;
    }
    hasHydratedQueuedMessagesRef.current = true;
  }, [isBootstrapping]);

  useEffect(() => {
    if (isBootstrapping || !hasHydratedQueuedMessagesRef.current) {
      return;
    }
    persistQueuedMessages(queueStorageKey(navigationScope, activeThread?.thread_id || null), queuedMessages);
  }, [activeThread?.thread_id, isBootstrapping, navigationScope, queuedMessages]);

  async function handleSend() {
    const input = composer.trim();
    if ((!input && !attachments.length) || hasInvalidAttachments(attachments)) {
      return;
    }
    const clientMessageId = crypto.randomUUID();
    setComposerError(null);
    let messageAttachments;
    try {
      messageAttachments = await Promise.all(attachments.map(uploadComposerAttachment));
    } catch (uploadError) {
      setComposerError(uploadError instanceof Error ? uploadError.message : "Unable to upload attachments.");
      return;
    }
    setComposer("");
    clearAttachments();
    const appReferences = mergeAppReferences(appReferencesFromText(input, mentionItems), activeAppContext);
    if (isRuntimeBusy || isSending) {
      setQueuedMessages((current) => [...current, { clientMessageId, content: input, attachments: messageAttachments, appReferences }]);
      return;
    }
    await submitMessage({ clientMessageId, content: input, attachments: messageAttachments, appReferences });
  }

  async function submitMessage(message: QueuedMessage) {
    setPendingUserMessages((current) => [
      ...current,
      {
        clientMessageId: message.clientMessageId,
        content: message.content,
        createdAt: new Date().toISOString(),
        attachments: message.attachments,
        appReferences: message.appReferences,
      },
    ]);
    setFailedUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
    setIsSending(true);
    setError(null);
    try {
      let thread = activeThread;
      if (!thread) {
        thread = await createChat({ resetView: false });
      } else if (!threads.some((item) => item.thread_id === thread?.thread_id)) {
        throw new Error("This chat no longer exists.");
      }
      if (!thread.runtime_session_id) {
        const session = await createRuntimeSession({
          system_prompt: promptWithActiveAppContext(thread.system_prompt, activeAppContext),
          source_app_id: "chat",
        });
        const updated = await updateThread({ thread_id: thread.thread_id, runtime_session_id: session.session_id });
        thread = updated.thread;
        setActiveThread(thread);
        setActiveSession(session);
        setThreads(updated.threads);
      }
      const response = await sendRuntimeTurn(
        thread.runtime_session_id,
        message.content,
        message.clientMessageId,
        message.attachments,
        message.appReferences,
      );
      setActiveSession(response.session);
      setActiveTurn(response.turn);
      setEvents((current) => mergeRuntimeEvents(current, response.events));
      if (response.turn.status !== "queued" && response.turn.status !== "active") {
        setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      }
      if (events.length === 0 && thread.title === "New chat") {
        const updated = await updateThread({ thread_id: thread.thread_id, title: firstUserTitle(message.content) });
        setActiveThread(updated.thread);
        setThreads(updated.threads);
      }
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
      setActiveTurn(null);
      setComposer(message.content);
      setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      setFailedUserMessages((current) => [
        ...current,
        {
          clientMessageId: message.clientMessageId,
          content: message.content,
          createdAt: new Date().toISOString(),
          attachments: message.attachments,
          appReferences: message.appReferences,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  useEffect(() => {
    if (isBootstrapping || isHistoryLoading || isRuntimeBusy || isSending || queuedMessages.length === 0) {
      return;
    }
    const [nextMessage, ...remainingMessages] = queuedMessages;
    setQueuedMessages(remainingMessages);
    void submitMessage(nextMessage);
  }, [isBootstrapping, isHistoryLoading, isRuntimeBusy, isSending, queuedMessages]);

  function handleAddAttachments(files: File[]) {
    addAttachments(files);
    setComposerError(null);
  }

  function handleCapturePageArea() {
    window.parent?.postMessage(
      {
        type: "maverick.shell.capture-area.start",
        owner_app_id: "chat",
        widget_id: "chat-floating",
        navigation_scope: navigationScope,
      },
      window.location.origin,
    );
  }

  async function handleStopTurn() {
    if (!activeTurn || !canStopTurn) {
      return;
    }
    try {
      const response = await interruptRuntimeTurn(activeTurn.turn_id);
      setActiveTurn(response.turn);
      if (response.event) {
        setEvents((current) => mergeRuntimeEvents(current, [response.event as RuntimeEvent]));
      }
      setError(null);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : "Unable to stop runtime turn.");
    }
  }

  return (
    <main className="chatapp-root">
      <section className="chatapp-chat-panel">
        <ChatHeader
          activeProviderId={activeProviderId}
          disabled={isBootstrapping || isSending}
          executionMode={executionMode}
          onSelectProvider={handleSelectProvider}
          providers={providers}
        />

        <div className="chatapp-chat-workspace">
          <div className="chatapp-chat-main">
            <ChatTranscript
              activeThread={activeThread}
              error={error}
              isLoading={isRuntimeBusy || isBootstrapping || isHistoryLoading}
              loadingLabel={loadingLabel}
              mentionItems={mentionItems}
              messages={messages}
            />
            <ChatComposer
              attachments={attachments}
              canStopTurn={canStopTurn}
              disabled={isBootstrapping || isHistoryLoading}
              error={composerError}
              isSending={isRuntimeBusy || isSending}
              mentionItems={mentionItems}
              onAddAttachments={handleAddAttachments}
              onCapturePageArea={enablePageCapture ? handleCapturePageArea : undefined}
              onChange={setComposer}
              onRemoveAttachment={removeAttachment}
              onStopTurn={handleStopTurn}
              onSubmit={handleSend}
              queuedCount={queuedMessages.length}
              queuedPreview={queuedMessages[0]?.content || null}
              value={composer}
            />
          </div>
        </div>
      </section>
    </main>
  );
}

function runtimeSessionThreadMetadataFromParams(params: Record<string, string | boolean | null>): RuntimeSessionThreadMetadata {
  const agentLabel = scalarString(params.agent_label);
  const threadTitle = scalarString(params.thread_title) || agentLabel;
  return {
    agent_label: agentLabel,
    agent_type_id: scalarString(params.agent_type_id),
    agent_role_id: scalarString(params.agent_role_id),
    source_app_id: scalarString(params.source_app_id) || "agents",
    title: threadTitle,
  };
}

function consumeNewChatRequest(
  params: Record<string, string | boolean | null>,
  consumedRequestIds: Set<string>,
  consumedLegacyRequest: MutableRefObject<boolean>,
): boolean {
  const requestId = scalarString(params.new_chat_request_id);
  if (!requestId) {
    if (consumedLegacyRequest.current) {
      return false;
    }
    consumedLegacyRequest.current = true;
    return true;
  }
  if (consumedRequestIds.has(requestId)) {
    return false;
  }
  consumedRequestIds.add(requestId);
  return true;
}

async function loadWidgetActiveAppContext(): Promise<ActiveAppContext | null> {
  const token = new URLSearchParams(window.location.search).get("context");
  if (!token) {
    return null;
  }
  try {
    const payload = await getWidgetContext(token);
    return activeAppContextFromWidgetContext(payload.context);
  } catch {
    return null;
  }
}

async function loadDefaultSystemPrompt(activeApp: ActiveAppContext | null): Promise<string> {
  try {
    return promptWithActiveAppContext(await getAgentsCommonPrompt(), activeApp);
  } catch {
    return promptWithActiveAppContext("", activeApp);
  }
}

function activeAppContextFromWidgetContext(context: Record<string, unknown>): ActiveAppContext | null {
  const content = context.content;
  if (!content || typeof content !== "object") {
    return null;
  }
  const payload = (content as { payload?: unknown }).payload;
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const activeApp = (payload as { active_app?: unknown }).active_app;
  if (!activeApp || typeof activeApp !== "object") {
    return null;
  }
  const record = activeApp as Record<string, unknown>;
  const appId = typeof record.app_id === "string" ? record.app_id.trim() : "";
  if (!appId || appId === "chat") {
    return null;
  }
  return {
    app_id: appId,
    description: typeof record.description === "string" ? record.description : "",
    name: typeof record.name === "string" && record.name.trim() ? record.name.trim() : appId,
    views: Array.isArray(record.views) ? record.views.filter((item): item is string => typeof item === "string") : [],
  };
}

function promptWithActiveAppContext(basePrompt: string, activeApp: ActiveAppContext | null): string {
  if (!activeApp) {
    return basePrompt;
  }
  if (basePrompt.includes(`active_app_id: ${activeApp.app_id}`)) {
    return basePrompt;
  }
  const lines = [
    "Current shell context:",
    `- active_app_id: ${activeApp.app_id}`,
    `- active_app_name: ${activeApp.name}`,
  ];
  if (activeApp.description) {
    lines.push(`- active_app_description: ${activeApp.description}`);
  }
  return [basePrompt.trim(), lines.join("\n")].filter(Boolean).join("\n\n");
}

function mergeAppReferences(references: AppReference[], activeApp: ActiveAppContext | null): AppReference[] {
  if (!activeApp || references.some((reference) => reference.app_id === activeApp.app_id)) {
    return references;
  }
  return [...references, { type: "app", app_id: activeApp.app_id, label: activeApp.name }];
}

function scalarString(value: string | boolean | null | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function queueStorageKey(navigationScope: string, threadId: string | null): string {
  return `${QUEUED_MESSAGES_STORAGE_PREFIX}:${navigationScope || "main"}:${threadId || "new"}`;
}

function runtimeHistoryCacheKey(navigationScope: string, runtimeSessionId: string): string {
  return `${RUNTIME_HISTORY_CACHE_STORAGE_PREFIX}:${navigationScope || "main"}:${runtimeSessionId}`;
}

function readRuntimeHistoryCache(storageKey: string): RuntimeHistoryCacheEntry | null {
  try {
    const rawValue = window.sessionStorage.getItem(storageKey);
    if (!rawValue) {
      return null;
    }
    const payload = JSON.parse(rawValue) as { activeTurn?: unknown; events?: unknown[]; session?: unknown; version?: unknown };
    if (payload.version !== 1 || !Array.isArray(payload.events)) {
      return null;
    }
    const session = isRuntimeSession(payload.session) ? payload.session : null;
    return {
      activeTurn: isRuntimeTurn(payload.activeTurn) ? payload.activeTurn : null,
      events: payload.events.filter(isRuntimeEvent),
      session,
    };
  } catch {
    return null;
  }
}

function persistRuntimeHistoryCache(storageKey: string, cacheEntry: RuntimeHistoryCacheEntry) {
  try {
    if (!cacheEntry.session && cacheEntry.events.length === 0) {
      window.sessionStorage.removeItem(storageKey);
      return;
    }
    window.sessionStorage.setItem(
      storageKey,
      JSON.stringify({
        version: 1,
        activeTurn: cacheEntry.activeTurn,
        events: sanitizeRuntimeEventsForCache(cacheEntry.events).slice(-RUNTIME_HISTORY_CACHE_EVENT_LIMIT),
        session: cacheEntry.session,
      }),
    );
  } catch {
    // History cache is an optimization for reloads; live HTTP/WebSocket history remains authoritative.
  }
}

function sanitizeRuntimeEventsForCache(events: RuntimeEvent[]): RuntimeEvent[] {
  return events.map((event) => {
    if (event.event_type !== "runtime.step.updated") {
      return event;
    }
    const payload = { ...event.payload };
    delete payload.raw;
    return { ...event, payload };
  });
}

function isRuntimeSession(value: unknown): value is RuntimeSession {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.session_id === "string" && typeof record.workspace_id === "string" && typeof record.agent_id === "string" && typeof record.status === "string";
}

function isRuntimeTurn(value: unknown): value is RuntimeTurn {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.turn_id === "string" && typeof record.session_id === "string" && typeof record.status === "string";
}

function isRuntimeEvent(value: unknown): value is RuntimeEvent {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.event_id === "string" &&
    typeof record.session_id === "string" &&
    (typeof record.turn_id === "string" || record.turn_id === null) &&
    typeof record.event_type === "string" &&
    Boolean(record.payload) &&
    typeof record.payload === "object" &&
    typeof record.created_at === "string"
  );
}

function readPersistedQueuedMessages(storageKey: string): QueuedMessage[] {
  try {
    const rawValue = window.localStorage.getItem(storageKey);
    if (!rawValue) {
      return [];
    }
    const payload = JSON.parse(rawValue) as { items?: unknown[]; version?: unknown };
    if (payload.version !== 1 || !Array.isArray(payload.items)) {
      return [];
    }
    return payload.items
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null;
        }
        const record = item as Record<string, unknown>;
        const clientMessageId = typeof record.clientMessageId === "string" ? record.clientMessageId : "";
        const content = typeof record.content === "string" ? record.content : "";
        const attachments = Array.isArray(record.attachments) ? record.attachments.filter(isPersistedMessageAttachment) : [];
        if (!clientMessageId || (!content.trim() && !attachments.length)) {
          return null;
        }
        return {
          clientMessageId,
          content,
          appReferences: persistedAppReferences(record.appReferences),
          attachments,
        };
      })
      .filter((item): item is QueuedMessage => Boolean(item));
  } catch {
    return [];
  }
}

function persistQueuedMessages(storageKey: string, queuedMessages: QueuedMessage[]) {
  try {
    if (!queuedMessages.length) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({
        version: 1,
        items: queuedMessages.map((message) => ({
          ...message,
          attachments: message.attachments.map((attachment) => ({ ...attachment, objectUrl: null })),
        })),
      }),
    );
  } catch {
    // Queue persistence is best-effort; in-memory sending remains the source of truth.
  }
}

function persistedAppReferences(value: unknown): AppReference[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      type: "app" as const,
      app_id: typeof item.app_id === "string" ? item.app_id : "",
      label: typeof item.label === "string" ? item.label : undefined,
    }))
    .filter((item) => item.app_id);
}

function isPersistedMessageAttachment(value: unknown): value is ChatMessageAttachment {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.name === "string" && typeof record.size === "number" && typeof record.type === "string";
}

function notifyAppDataChanged(ownerAppId: string, resource: string, detail: Record<string, string> = {}) {
  window.parent?.postMessage(
    {
      type: "maverick.app.data-changed",
      owner_app_id: ownerAppId,
      resource,
      ...detail,
    },
    window.location.origin,
  );
}

function debugThreadSync(label: string, detail: Record<string, unknown> = {}) {
  try {
    if (window.localStorage.getItem(THREAD_SYNC_DEBUG_STORAGE_KEY) !== "1") {
      return;
    }
    console.debug(`[chat thread-sync] ${label}`, {
      at: new Date().toISOString(),
      ...detail,
    });
  } catch {
    // Debug logging must never affect chat behavior.
  }
}
