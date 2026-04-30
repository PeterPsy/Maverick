import { type FormEvent, type MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import {
  ChatMessageAttachment,
  ChatThread,
  createRuntimeSession,
  createThread,
  AppReference,
  deleteThread,
  isRuntimeSessionUnavailableError,
  getWidgetContext,
  interruptRuntimeTurn,
  listApps,
  listProviders,
  listSkills,
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
import { useRuntimeThreads } from "./hooks/useRuntimeThreads";
import { hasInvalidAttachments } from "./lib/attachments";
import { appReferencesFromText } from "./lib/mentions";
import type { MentionItem } from "./lib/mentions";
import { PendingMessage, QueuedMessage, uploadComposerAttachment } from "./lib/messageState";
import { mergeRuntimeEvents } from "./lib/runtimeEvents";
import { latestRuntimeStepLabel } from "./lib/runtimeStepLabels";
import { openChatRootRouteInShell, openChatThreadRouteInShell } from "./lib/shellNavigation";
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

type DeleteConfirmation =
  | { kind: "single"; thread: ChatThread }
  | { kind: "all"; count: number };

type DeleteProgress = {
  completed: number;
  currentTitle: string;
  total: number;
};

const MESSAGE_HISTORY_LIMIT = 50;
const QUEUED_MESSAGES_STORAGE_PREFIX = "maverick.chat.queued-messages.v1";
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
  const [activeProviderId, setActiveProviderId] = useState("");
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
  const [threadsLoaded, setThreadsLoaded] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [activeAppContext, setActiveAppContext] = useState<ActiveAppContext | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState<DeleteConfirmation | null>(null);
  const [deleteProgress, setDeleteProgress] = useState<DeleteProgress | null>(null);
  const consumedNewChatRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewChatRequest = useRef(false);
  const initialSelectionHandledRef = useRef(false);
  const navigationRequestRef = useRef<string | null>(null);
  const lastPublishedRuntimeBusyState = useRef<string | null>(null);
  const availabilitySyncRequestRef = useRef(0);
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
  const showAppSidebar = !navigationScope;
  const isDeletingChats = Boolean(deleteProgress);
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
    onRuntimeSessionUnavailable: handleUnavailableRuntimeSession,
    onRuntimeSnapshot: () => setIsHistoryLoading(false),
    runtimeSessionId: activeThread?.runtime_session_id || null,
    setActiveSession,
    setActiveTurn,
    setError,
    setEvents,
    setPendingUserMessages,
  });

  useRuntimeThreads({
    onSnapshot: () => setThreadsLoaded(true),
    setError,
    setThreads,
  });

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id;
    activeRuntimeSessionIdRef.current = runtimeSessionId || null;
  }, [activeThread?.runtime_session_id]);

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
    const nextAvailability = isRuntimeBusy ? "busy" : "free";
    const currentThreadId = activeThread.thread_id;
    if (activeThread.availability !== nextAvailability) {
      const requestId = availabilitySyncRequestRef.current + 1;
      availabilitySyncRequestRef.current = requestId;
      void updateThread({ thread_id: currentThreadId, availability: nextAvailability })
        .then((payload) => {
          if (availabilitySyncRequestRef.current !== requestId) {
            return;
          }
          setThreads(payload.threads);
          setActiveThread((current) => (current?.thread_id === payload.thread.thread_id ? payload.thread : current));
          notifyActiveThreadChanged(payload.thread.thread_id);
        })
        .catch((syncError) => {
          setError((current) => current || (syncError instanceof Error ? syncError.message : "Unable to sync thread availability."));
        });
      return;
    }
    notifyActiveThreadChanged(currentThreadId);
  }, [activeThread?.availability, activeThread?.thread_id, isRuntimeBusy]);

  async function loadInitialState() {
    setIsBootstrapping(true);
    try {
      const widgetActiveAppContext = await loadWidgetActiveAppContext();
      setActiveAppContext(widgetActiveAppContext);
      const providerPayload = await listProviders();
      setProviders(providerPayload.items || providerPayload.available_providers || (providerPayload.active_provider ? [providerPayload.active_provider] : []));
      setActiveProviderId(providerPayload.active_provider?.provider_id || "");
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat.");
    }
  }

  useEffect(() => {
    loadInitialState();
    void loadMentionItems();
  }, []);

  useEffect(() => {
    if (!threadsLoaded || initialSelectionHandledRef.current) {
      return;
    }
    initialSelectionHandledRef.current = true;
    void selectInitialThread();
  }, [threadsLoaded, threads]);

  async function selectInitialThread() {
    try {
      const query = new URLSearchParams(window.location.search);
      if (query.get("new_chat") === "1") {
        const firstThread = await createChat({ activeAppContext, projectId: query.get("project_id") });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, firstThread?.thread_id || null)));
        setError(null);
        return;
      }
      const requestedThreadId = threadId || query.get("thread_id");
      const firstThread = requestedThreadId ? threads.find((thread) => thread.thread_id === requestedThreadId) || threads[0] || null : threads[0] || null;
      await selectThreadWithoutHttp(firstThread);
      setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, firstThread?.thread_id || null)));
      setError(null);
    } catch (selectionError) {
      setError(selectionError instanceof Error ? selectionError.message : "Unable to load chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

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
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "chat" }, window.location.origin);
  }, []);

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
      if (payload.type !== "maverick.app.navigate" || (payload.app_id && payload.app_id !== "chat")) {
        return;
      }
      void handleNavigationParams(payload.params || {});
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [activeThread?.thread_id, threads]);

  async function handleUnavailableRuntimeSession(runtimeSessionId: string) {
    if (!runtimeSessionId) {
      return;
    }
    if (activeRuntimeSessionIdRef.current === runtimeSessionId) {
      activeRuntimeSessionIdRef.current = null;
      setActiveSession(null);
      setEvents([]);
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

  async function handleSelectProvider(providerId: string) {
    setActiveProviderId(providerId);
    try {
      const payload = await selectProvider(providerId);
      setActiveProviderId(payload.active_provider?.provider_id || providerId);
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
    const session = await createRuntimeSession({
      project_id: projectId,
      source_app_id: "chat",
      system_prompt: systemPrompt,
      title: "New chat",
    });
    const payload = await createThread(session.session_id, projectId, { source_app_id: "chat", system_prompt: systemPrompt, title: "New chat" });
    setThreads(payload.threads);
    setActiveThread(payload.thread);
    setActiveSession(session);
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
    notifyActiveThreadChanged(payload.thread.thread_id);
    openChatThreadRouteInShell(payload.thread.thread_id, { navigationScope });
    return payload.thread;
  }

  async function selectThreadWithoutHttp(thread: ChatThread | null) {
    setIsHistoryLoading(Boolean(thread?.runtime_session_id));
    setActiveThread(thread);
    activeRuntimeSessionIdRef.current = thread?.runtime_session_id || null;
    setActiveSession(null);
    setEvents([]);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
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
        await createChat({ projectId: newChatProjectId });
      } else if (requestedThreadId) {
        suppressedExternalThreadIdRef.current = null;
        await openThreadById(requestedThreadId);
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

  async function openThreadById(threadId: string) {
    if (activeThread?.thread_id === threadId) {
      return;
    }
    const existingThread = threads.find((thread) => thread.thread_id === threadId);
    if (existingThread) {
      await handleSelectThread(existingThread);
      return;
    }
    const fallbackThread = threads[0] || null;
    if (fallbackThread) {
      await handleSelectThread(fallbackThread);
      return;
    }
    resetActiveConversation();
  }

  function notifyActiveThreadChanged(activeThreadId: string) {
    debugThreadSync("app-notify-active-thread", {
      activeThreadId: activeThread?.thread_id || "",
      nextActiveThreadId: activeThreadId,
      navigationScope,
      threadId,
    });
    window.parent?.postMessage(
      {
        type: "maverick.chat.active-thread-changed",
        owner_app_id: "chat",
        active_thread_id: activeThreadId,
        ...(navigationScope ? { navigation_scope: navigationScope } : {}),
      },
      window.location.origin,
    );
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
        throw new Error("This chat does not have a runtime session.");
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

  async function renameSidebarThread(threadId: string, title: string) {
    const trimmedTitle = title.trim();
    if (!threadId || !trimmedTitle) {
      return;
    }
    try {
      const payload = await updateThread({ thread_id: threadId, title: trimmedTitle });
      setThreads(payload.threads);
      setActiveThread((current) => (current?.thread_id === payload.thread.thread_id ? payload.thread : current));
      setError(null);
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "Unable to rename chat.");
    }
  }

  async function deleteSidebarThread(thread: ChatThread) {
    try {
      const payload = await deleteThread(thread.thread_id);
      setThreads(payload.threads);
      if (activeThread?.thread_id === thread.thread_id) {
        resetActiveConversation();
        const nextThread = payload.threads[0] || null;
        if (nextThread) {
          await handleSelectThread(nextThread);
        } else {
          openChatRootRouteInShell({ navigationScope });
        }
      }
      setError(null);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete chat.");
    }
  }

  async function deleteAllSidebarThreads(targetThreads: ChatThread[]) {
    if (!targetThreads.length) {
      return;
    }
    resetActiveConversation();
    openChatRootRouteInShell({ navigationScope });
    setDeleteProgress({ completed: 0, currentTitle: targetThreads[0]?.title || "New chat", total: targetThreads.length });
    try {
      let latestThreads = threads;
      for (const [index, thread] of targetThreads.entries()) {
        setDeleteProgress({ completed: index, currentTitle: thread.title || "New chat", total: targetThreads.length });
        try {
          const payload = await deleteThread(thread.thread_id);
          latestThreads = payload.threads;
          setThreads(payload.threads);
        } catch (threadDeleteError) {
          throw threadDeleteError;
        }
      }
      setThreads(latestThreads);
      setDeleteProgress({ completed: targetThreads.length, currentTitle: "Complete", total: targetThreads.length });
      setError(null);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete chats.");
    } finally {
      window.setTimeout(() => {
        setDeleteProgress(null);
        setDeleteConfirmation(null);
      }, 300);
    }
  }

  async function confirmDeleteSelection() {
    const selection = deleteConfirmation;
    if (!selection || deleteProgress) {
      return;
    }
    if (selection.kind === "single") {
      setDeleteConfirmation(null);
      await deleteSidebarThread(selection.thread);
      return;
    }
    await deleteAllSidebarThreads([...threads]);
  }

  return (
    <main className={`chatapp-root ${showAppSidebar ? "chatapp-root--with-sidebar" : ""}`}>
      {showAppSidebar ? (
        <ChatAppSidebar
          activeThreadId={activeThread?.thread_id || ""}
          disabled={isBootstrapping || isHistoryLoading || isSending || isDeletingChats}
          onCreateChat={() => {
            void createChat();
          }}
          onDeleteAllThreads={() => {
            setDeleteConfirmation({ kind: "all", count: threads.length });
          }}
          onSelectThread={(thread) => {
            void handleSelectThread(thread);
          }}
          onDeleteThread={(thread) => {
            setDeleteConfirmation({ kind: "single", thread });
          }}
          onRenameThread={(threadId, title) => {
            void renameSidebarThread(threadId, title);
          }}
          threads={threads}
        />
      ) : null}
      <section className="chatapp-chat-panel">
        <ChatHeader
          activeProviderId={activeProviderId}
          disabled={isBootstrapping || isSending || isDeletingChats}
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
              disabled={isBootstrapping || isHistoryLoading || isDeletingChats}
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
      {deleteConfirmation ? (
        <DeleteChatsDialog
          confirmation={deleteConfirmation}
          disabled={isBootstrapping || isHistoryLoading || isSending || isDeletingChats}
          onCancel={() => setDeleteConfirmation(null)}
          onConfirm={() => {
            void confirmDeleteSelection();
          }}
          progress={deleteProgress}
        />
      ) : null}
    </main>
  );
}

function DeleteChatsDialog({
  confirmation,
  disabled,
  onCancel,
  onConfirm,
  progress,
}: {
  confirmation: DeleteConfirmation;
  disabled: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  progress: DeleteProgress | null;
}) {
  const isSingle = confirmation.kind === "single";
  const isDeleting = Boolean(progress);
  const progressPercent = progress && progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0;
  const title = isSingle ? `Delete "${confirmation.thread.title || "New chat"}"?` : "Delete all chats?";
  const description = isSingle
    ? "This removes the chat, runtime history, provider state, and session files for this conversation."
    : `This removes ${confirmation.count} chats, their runtime history, provider state, and session files.`;

  return (
    <div className="chatapp-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="chat-delete-title">
      <button className="chatapp-delete-dialog__backdrop" disabled={isDeleting} type="button" aria-label="Cancel delete" onClick={onCancel} />
      <section className="chatapp-delete-dialog__panel">
        <header>
          <span className="material-symbols-rounded" aria-hidden="true">{isDeleting ? "progress_activity" : "warning"}</span>
          <div>
            <h2 id="chat-delete-title">{title}</h2>
            <p>{progress ? `Deleting ${progress.currentTitle}` : description}</p>
          </div>
        </header>
        {progress ? (
          <div className="chatapp-delete-dialog__progress">
            <div
              className="chatapp-delete-dialog__progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={progress.total}
              aria-valuenow={progress.completed}
            >
              <span style={{ width: `${progressPercent}%` }} />
            </div>
            <small>{progress.completed} / {progress.total}</small>
          </div>
        ) : null}
        <div className="chatapp-delete-dialog__actions">
          <button className="chatapp-delete-dialog__secondary" disabled={isDeleting} type="button" onClick={onCancel}>
            Cancel
          </button>
          <button className="chatapp-delete-dialog__danger" disabled={disabled} type="button" onClick={onConfirm}>
            {isDeleting ? "Deleting" : "Delete"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ChatAppSidebar({
  activeThreadId,
  disabled,
  onCreateChat,
  onDeleteAllThreads,
  onDeleteThread,
  onRenameThread,
  onSelectThread,
  threads,
}: {
  activeThreadId: string;
  disabled: boolean;
  onCreateChat: () => void;
  onDeleteAllThreads: () => void;
  onDeleteThread: (thread: ChatThread) => void;
  onRenameThread: (threadId: string, title: string) => void;
  onSelectThread: (thread: ChatThread) => void;
  threads: ChatThread[];
}) {
  const [renamingThreadId, setRenamingThreadId] = useState("");
  const [renamingTitle, setRenamingTitle] = useState("");

  function startRename(thread: ChatThread) {
    setRenamingThreadId(thread.thread_id);
    setRenamingTitle(thread.title || "New chat");
  }

  function submitRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const threadId = renamingThreadId;
    const title = renamingTitle.trim();
    setRenamingThreadId("");
    setRenamingTitle("");
    if (threadId && title) {
      onRenameThread(threadId, title);
    }
  }

  function cancelRename() {
    setRenamingThreadId("");
    setRenamingTitle("");
  }

  return (
    <aside className="chatapp-app-sidebar" aria-label="Chat list">
      <div className="chatapp-app-sidebar__header">
        <div>
          <p>Chat</p>
          <strong>{threads.length}</strong>
        </div>
        <div className="chatapp-app-sidebar__header-actions">
          <button aria-label="Delete all chats" className="is-danger" disabled={disabled || !threads.length} onClick={onDeleteAllThreads} type="button">
            <span className="material-symbols-rounded" aria-hidden="true">delete_sweep</span>
          </button>
          <button aria-label="New chat" disabled={disabled} onClick={onCreateChat} type="button">
            <span className="material-symbols-rounded" aria-hidden="true">add</span>
          </button>
        </div>
      </div>
      <div className="chatapp-app-sidebar__list">
        {threads.map((thread) => {
          const isActive = activeThreadId === thread.thread_id;
          const isBusy = thread.availability === "busy" || thread.availability === "queued" || thread.availability === "active";
          return (
            <div
              className={`chatapp-app-sidebar__thread ${isActive ? "is-active" : ""} ${isBusy ? "is-busy" : ""}`}
              key={thread.thread_id}
            >
              {renamingThreadId === thread.thread_id ? (
                <form className="chatapp-app-sidebar__rename-form" onSubmit={submitRename}>
                  <input
                    aria-label={`Rename ${thread.title || "New chat"}`}
                    autoFocus
                    value={renamingTitle}
                    onChange={(event) => setRenamingTitle(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        cancelRename();
                      }
                    }}
                  />
                  <button className="chatapp-app-sidebar__action" disabled={disabled} type="submit" aria-label="Save chat name">
                    <span className="material-symbols-rounded" aria-hidden="true">check</span>
                  </button>
                  <button className="chatapp-app-sidebar__action" type="button" onClick={cancelRename} aria-label="Cancel chat rename">
                    <span className="material-symbols-rounded" aria-hidden="true">close</span>
                  </button>
                </form>
              ) : (
                <>
                  <button
                    className="chatapp-app-sidebar__thread-main"
                    disabled={disabled && !isActive}
                    onClick={() => onSelectThread(thread)}
                    type="button"
                  >
                    <span className="chatapp-app-sidebar__thread-icon material-symbols-rounded" aria-hidden="true">chat_bubble</span>
                    <span className="chatapp-app-sidebar__thread-copy">
                      <strong>{thread.title || "New chat"}</strong>
                      <small>{threadSidebarMeta(thread)}</small>
                    </span>
                  </button>
                  <div className="chatapp-app-sidebar__actions" aria-label={`${thread.title || "New chat"} chat actions`}>
                    <button className="chatapp-app-sidebar__action" disabled={disabled} type="button" onClick={() => startRename(thread)} aria-label={`Rename ${thread.title || "New chat"}`}>
                      <span className="material-symbols-rounded" aria-hidden="true">edit</span>
                    </button>
                    <button className="chatapp-app-sidebar__action is-danger" disabled={disabled} type="button" onClick={() => onDeleteThread(thread)} aria-label={`Delete ${thread.title || "New chat"}`}>
                      <span className="material-symbols-rounded" aria-hidden="true">delete</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
        {!threads.length ? <p className="chatapp-app-sidebar__empty">No chats yet.</p> : null}
      </div>
    </aside>
  );
}

function threadSidebarMeta(thread: ChatThread) {
  if (thread.availability && thread.availability !== "free") {
    return thread.availability;
  }
  if (thread.agent_label) {
    return thread.agent_label;
  }
  return formatThreadDate(thread.updated_at || thread.created_at);
}

function formatThreadDate(value: string) {
  if (!value) {
    return "No activity";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No activity";
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function runtimeSessionThreadMetadataFromParams(params: Record<string, string | boolean | null>): RuntimeSessionThreadMetadata {
  const agentLabel = scalarString(params.agent_label);
  const threadTitle = scalarString(params.thread_title) || agentLabel;
  return {
    agent_label: agentLabel,
    agent_type_id: scalarString(params.agent_type_id),
    agent_role_id: scalarString(params.agent_role_id),
    source_app_id: scalarString(params.source_app_id) || "chat",
    title: threadTitle,
  };
}

function normalizeChatRouteParams(params: Record<string, string | boolean | null>): Record<string, string | boolean | null> {
  const appPage = scalarString(params.app_page);
  if (!appPage) {
    return params;
  }
  const [kind, id] = appPage.split("/").filter(Boolean);
  if (kind === "threads" && id) {
    return { ...params, thread_id: id };
  }
  if (kind === "runtime-sessions" && id) {
    return { ...params, runtime_session_id: id };
  }
  return params;
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
  const token = widgetContextToken();
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

function widgetContextToken(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("context") || new URLSearchParams(window.location.search).get("context") || "";
}

async function loadDefaultSystemPrompt(activeApp: ActiveAppContext | null): Promise<string> {
  return promptWithActiveAppContext("", activeApp);
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

function chatNavigationRequestKey({
  newChatProjectId,
  requestedRuntimeSessionId,
  requestedThreadId,
  shouldCreateChat,
}: {
  newChatProjectId: string | null;
  requestedRuntimeSessionId: string | null;
  requestedThreadId: string | null;
  shouldCreateChat: boolean;
}) {
  return JSON.stringify({
    new_chat: shouldCreateChat,
    project_id: newChatProjectId || "",
    runtime_session_id: requestedRuntimeSessionId || "",
    thread_id: requestedThreadId || "",
  });
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
