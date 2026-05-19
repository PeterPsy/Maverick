import { type CSSProperties, type DragEvent, type MutableRefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppDependenciesPayload,
  AgentTypeSummary,
  ChatMessageAttachment,
  ChatThread,
  createRuntimeSessionWithTurn,
  createThread,
  getAgentDefinition,
  getAppDependencies,
  getSpeechCapabilities,
  AppReference,
  isRuntimeSessionUnavailableError,
  getWidgetContext,
  interruptRuntimeTurn,
  listAgentCatalog,
  listApps,
  listProviders,
  listSkills,
  markThreadRead,
  previewAgentPrompt,
  ProviderItem,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  orderChatThreads,
  selectProvider,
  selectedDependencyProviderAppId,
  selectedSharedDependencyProviderAppId,
  sendRuntimeTurn,
} from "./api/client";
import { ChatComposer } from "./components/ChatComposer";
import { ChatTranscript } from "./components/ChatTranscript";
import { useComposerAttachments } from "./hooks/useComposerAttachments";
import { useRuntimeEvents } from "./hooks/useRuntimeEvents";
import { useRuntimeThreads } from "./hooks/useRuntimeThreads";
import { hasInvalidAttachments } from "./lib/attachments";
import { filesFromDataTransfer, hasFileDropData } from "./lib/fileDropAttachments";
import { appReferencesFromText, mentionText, referenceKey } from "./lib/mentions";
import type { MentionItem } from "./lib/mentions";
import { PendingMessage, QueuedMessage, uploadComposerAttachment } from "./lib/messageState";
import { mergeRuntimeEvents } from "./lib/runtimeEvents";
import { searchComposerReferences } from "./lib/referenceSearch";
import {
  deleteStoredRuntimeTranscript,
  readStoredRuntimeTranscript,
  type RuntimeTranscriptCacheEntry,
  writeStoredRuntimeTranscript,
} from "./lib/runtimeTranscriptCache";
import { latestRuntimeStepLabel } from "./lib/runtimeStepLabels";
import { openChatRootRouteInShell, openChatThreadRouteInShell } from "./lib/shellNavigation";
import { findThreadByRuntimeSession } from "./lib/threadNavigation";
import { eventsToMessages } from "./lib/transcript";

type ShellNavigationMessage = {
  type?: string;
  context?: Record<string, unknown>;
  deleted_thread_id?: string;
  error?: string;
  files?: unknown[];
  dependencies?: AppDependenciesPayload;
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

type DraftChat = {
  projectId: string | null;
  systemPrompt: string;
};

type AgentRuntimeConfig = {
  agent_id: string;
  agent_role_id: string;
  agent_type_id: string;
  skill_ids: string[];
  source_app_id: string;
  system_prompt: string;
  title: string;
};

type ActiveAppContext = {
  app_id: string;
  description: string;
  name: string;
  views: string[];
};

export type ExternalMentionDrop = {
  items: MentionItem[];
  requestId: string;
};

export type ExternalFileDrop = {
  files: File[];
  requestId: string;
};

const MESSAGE_HISTORY_LIMIT = 50;
const AGENT_CATALOG_DEPENDENCY_ALIAS = "agent-catalog";
const AGENT_PROMPT_MATERIALIZER_DEPENDENCY_ALIAS = "agent-prompt-materializer";
const TEXT_TO_SPEECH_DEPENDENCY_ALIAS = "text-to-speech";
const QUEUED_MESSAGES_STORAGE_PREFIX = "maverick.chat.queued-messages.v1";
const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";

function isThreadAvailabilityBusy(availability: string) {
  return availability === "busy" || availability === "queued" || availability === "active";
}

export function App({
  enablePageCapture = false,
  externalFileDrop = null,
  externalMentionDrop = null,
  navigationScope = "",
  newChatProjectId = null,
  newChatRequestId = null,
  threadId = null,
}: {
  enablePageCapture?: boolean;
  externalFileDrop?: ExternalFileDrop | null;
  externalMentionDrop?: ExternalMentionDrop | null;
  navigationScope?: string;
  newChatProjectId?: string | null;
  newChatRequestId?: string | null;
  threadId?: string | null;
} = {}) {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [activeProviderId, setActiveProviderId] = useState("");
  const [agentCatalogAppId, setAgentCatalogAppId] = useState("");
  const [speechProviderAppId, setSpeechProviderAppId] = useState("");
  const [speechProviderAvailable, setSpeechProviderAvailable] = useState(false);
  const [speechMaxTextChars, setSpeechMaxTextChars] = useState(0);
  const [agentOptions, setAgentOptions] = useState<AgentTypeSummary[]>([]);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState("");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [draftChat, setDraftChat] = useState<DraftChat | null>(null);
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
  const [hasLoadedHistory, setHasLoadedHistory] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [selectedReferences, setSelectedReferences] = useState<AppReference[]>([]);
  const [activeAppContext, setActiveAppContext] = useState<ActiveAppContext | null>(null);
  const consumedExternalFileDrops = useRef<Set<string>>(new Set());
  const consumedNewChatRequests = useRef<Set<string>>(new Set());
  const consumedExternalMentionDrops = useRef<Set<string>>(new Set());
  const consumedLegacyNewChatRequest = useRef(false);
  const initialSelectionHandledRef = useRef(false);
  const navigationRequestRef = useRef<string | null>(null);
  const hasHydratedQueuedMessagesRef = useRef(false);
  const suppressedExternalThreadIdRef = useRef<string | null>(null);
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const activeRuntimeSessionIdRef = useRef<string | null>(null);
  const runtimeTranscriptCacheRef = useRef<Map<string, RuntimeTranscriptCacheEntry>>(new Map());
  const dockedComposerRef = useRef<HTMLDivElement | null>(null);
  const [dockedComposerHeight, setDockedComposerHeight] = useState(144);

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
  const executionMode = activeSession?.effective_mode === "sandbox" || activeSession?.effective_mode === "full-access" ? activeSession.effective_mode : null;
  const canStopTurn = activeTurn?.status === "queued" || activeTurn?.status === "active";
  const isRuntimeBusy = canStopTurn;
  const composerSelectedAgentTypeId = activeThread
    ? activeThread.source_app_id && activeThread.source_app_id !== "chat"
      ? activeThread.agent_type_id
      : ""
    : selectedAgentTypeId;
  const isTranscriptHistoryPending = Boolean(activeThread?.runtime_session_id && !hasLoadedHistory && messages.length === 0);
  const isEmptyChatView =
    Boolean(draftChat) && messages.length === 0 && !isRuntimeBusy && !isBootstrapping && !isHistoryLoading && !isTranscriptHistoryPending && !error;
  const isThreadLoading = isBootstrapping || isHistoryLoading || isTranscriptHistoryPending;
  const chatMainStyle = isEmptyChatView
    ? undefined
    : ({
        "--chatapp-composer-overlay-height": `${dockedComposerHeight}px`,
      } as CSSProperties);
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
  const composerMentionItems = useMemo(
    () => mergeSelectedReferenceMentionItems(mentionItems, selectedReferences),
    [mentionItems, selectedReferences],
  );

  useEffect(() => {
    const dock = dockedComposerRef.current;
    if (!dock || isEmptyChatView) {
      return;
    }
    const updateDockHeight = () => {
      setDockedComposerHeight(Math.ceil(dock.getBoundingClientRect().height));
    };
    updateDockHeight();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateDockHeight);
      return () => window.removeEventListener("resize", updateDockHeight);
    }
    const observer = new ResizeObserver(updateDockHeight);
    observer.observe(dock);
    return () => observer.disconnect();
  }, [attachments.length, composerError, isEmptyChatView, queuedMessages.length]);

  useRuntimeEvents({
    activeTurn,
    onRuntimeSessionUnavailable: handleUnavailableRuntimeSession,
    onRuntimeSnapshot: () => {
      setHasLoadedHistory(true);
      setIsHistoryLoading(false);
    },
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
    setActiveThread((current) => {
      if (!current) {
        return current;
      }
      return threads.find((thread) => thread.thread_id === current.thread_id) || current;
    });
  }, [threads]);

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

  async function loadInitialState() {
    setIsBootstrapping(true);
    try {
      const widgetActiveAppContext = await loadWidgetActiveAppContext();
      setActiveAppContext(widgetActiveAppContext);
      const [providerPayload] = await Promise.all([listProviders(), loadAppDependencies()]);
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

  async function loadAppDependencies() {
    try {
      const dependencies = await getAppDependencies("chat");
      await Promise.all([loadAgentOptionsFromDependencies(dependencies), loadSpeechProviderFromDependencies(dependencies)]);
    } catch {
      clearAgentOptions();
      clearSpeechProvider();
    }
  }

  async function loadAgentOptionsFromDependencies(dependencies: AppDependenciesPayload) {
    try {
      const providerAppId = selectedSharedDependencyProviderAppId(dependencies, [
        AGENT_CATALOG_DEPENDENCY_ALIAS,
        AGENT_PROMPT_MATERIALIZER_DEPENDENCY_ALIAS,
      ]);
      await loadAgentOptionsFromProvider(providerAppId);
    } catch {
      clearAgentOptions();
    }
  }

  async function loadAgentOptionsFromProvider(providerAppId: string) {
    if (!providerAppId) {
      clearAgentOptions();
      return;
    }
    const catalog = await listAgentCatalog(providerAppId);
    const nextAgentOptions = catalog.agent_types || [];
    setAgentCatalogAppId(providerAppId);
    setAgentOptions(nextAgentOptions);
    setSelectedAgentTypeId((current) => (current && !nextAgentOptions.some((agent) => agent.id === current) ? "" : current));
  }

  function clearAgentOptions() {
    setAgentCatalogAppId("");
    setAgentOptions([]);
    setSelectedAgentTypeId("");
  }

  async function loadSpeechProviderFromDependencies(dependencies: AppDependenciesPayload) {
    try {
      const providerAppId = selectedDependencyProviderAppId(dependencies, TEXT_TO_SPEECH_DEPENDENCY_ALIAS);
      if (!providerAppId) {
        clearSpeechProvider();
        return;
      }
      const capabilities = await getSpeechCapabilities(providerAppId);
      const synthesis = capabilities.interfaces?.["speech.synthesis"];
      if (!synthesis) {
        clearSpeechProvider();
        return;
      }
      const maxTextChars = typeof synthesis.max_text_chars === "number" && synthesis.max_text_chars > 0 ? synthesis.max_text_chars : 0;
      setSpeechProviderAppId(providerAppId);
      setSpeechProviderAvailable(Boolean(synthesis.available && synthesis.provider_available !== false));
      setSpeechMaxTextChars(maxTextChars);
    } catch {
      clearSpeechProvider();
    }
  }

  function clearSpeechProvider() {
    setSpeechProviderAppId("");
    setSpeechProviderAvailable(false);
    setSpeechMaxTextChars(0);
  }

  useEffect(() => {
    if (!externalMentionDrop || consumedExternalMentionDrops.current.has(externalMentionDrop.requestId)) {
      return;
    }
    consumedExternalMentionDrops.current.add(externalMentionDrop.requestId);
    appendMentionItemsToComposer(externalMentionDrop.items);
  }, [externalMentionDrop]);

  useEffect(() => {
    if (!externalFileDrop || consumedExternalFileDrops.current.has(externalFileDrop.requestId)) {
      return;
    }
    consumedExternalFileDrops.current.add(externalFileDrop.requestId);
    handleAddAttachments(externalFileDrop.files);
  }, [externalFileDrop]);

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
      if (newChatRequestId) {
        createDraftChat({ activeAppContext, projectId: newChatProjectId });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
        setError(null);
        return;
      }
      if (query.get("new_chat") === "1") {
        createDraftChat({ activeAppContext, projectId: query.get("project_id") });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
        setError(null);
        return;
      }
      const requestedThreadId = threadId || query.get("thread_id");
      const firstThread = requestedThreadId ? threads.find((thread) => thread.thread_id === requestedThreadId) || null : threads[0] || null;
      if (!firstThread) {
        if (requestedThreadId) {
          suppressedExternalThreadIdRef.current = requestedThreadId;
        }
        createDraftChat({ activeAppContext, resetView: false });
        setQueuedMessages(readPersistedQueuedMessages(queueStorageKey(navigationScope, null)));
        setError(null);
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
      if (payload.type === "maverick.app.dependencies" && payload.app_id === "chat" && payload.dependencies) {
        void Promise.all([loadAgentOptionsFromDependencies(payload.dependencies), loadSpeechProviderFromDependencies(payload.dependencies)]);
        return;
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === agentCatalogAppId && payload.resource === "configuration") {
        void loadAppDependencies();
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
  }, [activeThread?.thread_id, agentCatalogAppId, threads]);

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

  function handleSelectAgent(agentTypeId: string) {
    if (activeThread) {
      return;
    }
    setSelectedAgentTypeId(agentTypeId);
    setComposerError(null);
  }

  async function selectedAgentRuntimeConfig(activeApp: ActiveAppContext | null): Promise<AgentRuntimeConfig | null> {
    if (!selectedAgentTypeId || !agentCatalogAppId) {
      return null;
    }
    const [definitionPayload, promptPayload] = await Promise.all([
      getAgentDefinition(agentCatalogAppId, selectedAgentTypeId),
      previewAgentPrompt(agentCatalogAppId, selectedAgentTypeId),
    ]);
    const definition = definitionPayload.agent_definition;
    if (!definitionPayload.exists || !definition) {
      throw new Error("Selected agent is no longer available.");
    }
    return {
      agent_id: definition.name,
      agent_role_id: definition.role_id,
      agent_type_id: definition.id,
      skill_ids: definition.skill_ids || [],
      source_app_id: agentCatalogAppId,
      system_prompt: promptWithActiveAppContext(promptPayload.rendered || "", activeApp),
      title: definition.name,
    };
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

  function handleChatRootPointerDown() {
    void markActiveThreadReadIfNeeded(activeThread);
  }

  function handleChatRootDragOver(event: DragEvent<HTMLElement>) {
    if (isThreadLoading || !hasFileDropData(event.dataTransfer)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleChatRootDrop(event: DragEvent<HTMLElement>) {
    if (isThreadLoading) {
      return;
    }
    const files = filesFromDataTransfer(event.dataTransfer);
    if (!files.length) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    handleAddAttachments(files);
  }

  async function markActiveThreadReadIfNeeded(thread: ChatThread | null) {
    if (!thread?.has_unread_completed_response || readReceiptInFlightRef.current.has(thread.thread_id)) {
      return;
    }
    readReceiptInFlightRef.current.add(thread.thread_id);
    setActiveThread((current) => (current?.thread_id === thread.thread_id ? { ...current, has_unread_completed_response: false } : current));
    setThreads((current) =>
      current.map((item) => (item.thread_id === thread.thread_id ? { ...item, has_unread_completed_response: false } : item)),
    );
    try {
      const payload = await markThreadRead(thread.thread_id);
      setThreads(payload.threads);
      setActiveThread((current) => (current?.thread_id === payload.thread.thread_id ? payload.thread : current));
    } catch {
      // Reading an open chat should not be blocked by a best-effort receipt.
    } finally {
      readReceiptInFlightRef.current.delete(thread.thread_id);
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
    setSelectedReferences([]);
    clearAttachments();
    const appReferences = mergeAppReferences(appReferencesFromText(input, composerMentionItems), activeAppContext);
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
      let response: Awaited<ReturnType<typeof sendRuntimeTurn>>;
      if (!thread) {
        const agentRuntimeConfig = await selectedAgentRuntimeConfig(activeAppContext);
        const systemPrompt = agentRuntimeConfig?.system_prompt || draftChat?.systemPrompt || (await loadDefaultSystemPrompt(activeAppContext));
        response = await createRuntimeSessionWithTurn({
          appReferences: message.appReferences,
          attachments: message.attachments,
          clientMessageId: message.clientMessageId,
          inputText: message.content,
          options: {
            agent_id: agentRuntimeConfig?.agent_id,
            agent_role_id: agentRuntimeConfig?.agent_role_id,
            agent_type_id: agentRuntimeConfig?.agent_type_id,
            project_id: draftChat?.projectId ?? null,
            source_app_id: agentRuntimeConfig?.source_app_id || "chat",
            system_prompt: systemPrompt,
            skill_ids: agentRuntimeConfig?.skill_ids || [],
            title: agentRuntimeConfig?.title || "New chat",
          },
        });
        setDraftChat(null);
      } else if (!threads.some((item) => item.thread_id === thread?.thread_id)) {
        throw new Error("This chat no longer exists.");
      } else {
        if (!thread.runtime_session_id) {
          throw new Error("This chat does not have a runtime session.");
        }
        response = await sendRuntimeTurn(
          thread.runtime_session_id,
          message.content,
          message.clientMessageId,
          message.attachments,
          message.appReferences,
        );
      }
      const responseThread = response.thread;
      const baseThread = responseThread || thread;
      if (!baseThread) {
        throw new Error("Runtime thread was not created.");
      }
      setActiveSession(response.session);
      setActiveTurn(response.turn);
      setEvents((current) => mergeRuntimeEvents(current, response.events));
      const userMessageAt = response.turn.created_at || new Date().toISOString();
      const optimisticThread = {
        ...baseThread,
        ...(responseThread || {}),
        availability: response.turn.status === "queued" || response.turn.status === "active" ? response.turn.status : "free",
        last_user_message_at: userMessageAt,
      };
      setActiveThread((current) => (current?.thread_id === optimisticThread.thread_id ? { ...current, ...optimisticThread } : optimisticThread));
      setThreads((current) => upsertOrderedThread(current, optimisticThread));
      if (!thread) {
        notifyActiveThreadChanged(optimisticThread.thread_id);
        openChatThreadRouteInShell(optimisticThread.thread_id, { navigationScope });
      }
      if (response.turn.status !== "queued" && response.turn.status !== "active") {
        setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      }
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
      setActiveTurn(null);
      setComposer(message.content);
      setSelectedReferences(message.appReferences);
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

  function appendMentionItemsToComposer(items: MentionItem[]) {
    const validItems = items.filter((item) => item.reference);
    if (!validItems.length) {
      return;
    }
    const mentionBlock = validItems.map((item) => mentionText(item)).join(" ");
    setComposer((current) => {
      const prefix = current && !/\s$/.test(current) ? " " : "";
      return `${current}${prefix}${mentionBlock} `;
    });
    validItems.forEach((item) => {
      if (item.reference) {
        handleReferenceAdd(item.reference);
      }
    });
    setComposerError(null);
  }

  const handleSearchReferences = useCallback(
    async (query: string, signal: AbortSignal): Promise<MentionItem[]> => {
      const references = await searchComposerReferences(query, signal, activeAppContext?.app_id || "");
      return references.map(referenceMentionItem);
    },
    [activeAppContext?.app_id],
  );

  function handleReferenceAdd(reference: AppReference) {
    setSelectedReferences((current) => {
      const key = referenceKey(reference);
      return current.some((item) => referenceKey(item) === key) ? current : [...current, reference];
    });
  }

  function handleReferenceRemove(reference: AppReference) {
    const key = referenceKey(reference);
    setSelectedReferences((current) => current.filter((item) => referenceKey(item) !== key));
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
    <main className="chatapp-root" onDragOver={handleChatRootDragOver} onDrop={handleChatRootDrop} onPointerDown={handleChatRootPointerDown}>
      <section className="chatapp-chat-panel">
        <div className={`chatapp-chat-workspace ${isEmptyChatView ? "is-empty-chat" : ""}`}>
          <div className={`chatapp-chat-main ${isEmptyChatView ? "is-empty-chat" : ""}`} style={chatMainStyle}>
            {isEmptyChatView ? (
              <div className="chatapp-empty-chat-stage">
                <div className="chatapp-empty-chat-stage__copy">
                  <h1>How can I help today?</h1>
                  <span aria-hidden="true" />
                  <p>Type a command or ask Maverick a question</p>
                </div>
                <ChatComposer
                  activeProviderId={activeProviderId}
                  agentSelectorLocked={Boolean(activeThread)}
                  agents={agentOptions}
                  attachments={attachments}
                  canStopTurn={canStopTurn}
                  disabled={isThreadLoading}
                  error={composerError}
                  executionMode={executionMode}
                  isEmptyMode
                  isSending={isRuntimeBusy || isSending}
                  mentionItems={composerMentionItems}
                  onAddAttachments={handleAddAttachments}
                  onCapturePageArea={enablePageCapture ? handleCapturePageArea : undefined}
                  onChange={setComposer}
                  onReferenceAdd={handleReferenceAdd}
                  onReferenceRemove={handleReferenceRemove}
                  onSearchReferences={handleSearchReferences}
                  onSelectAgent={handleSelectAgent}
                  onSelectProvider={handleSelectProvider}
                  onRemoveAttachment={removeAttachment}
                  onStopTurn={handleStopTurn}
                  onSubmit={handleSend}
                  providers={providers}
                  queuedCount={queuedMessages.length}
                  queuedPreview={queuedMessages[0]?.content || null}
                  selectedAgentTypeId={composerSelectedAgentTypeId}
                  value={composer}
                />
              </div>
            ) : (
              <ChatTranscript
                error={error}
                isLoading={isRuntimeBusy || isThreadLoading}
                loadingLabel={loadingLabel}
                mentionItems={mentionItems}
                messages={messages}
                speechMaxTextChars={speechMaxTextChars}
                speechProviderAvailable={speechProviderAvailable}
                speechProviderAppId={speechProviderAppId}
              />
            )}
            {!isEmptyChatView ? (
              <div className="chatapp-composer-dock" ref={dockedComposerRef}>
                <ChatComposer
                  activeProviderId={activeProviderId}
                  agentSelectorLocked={Boolean(activeThread)}
                  agents={agentOptions}
                  attachments={attachments}
                  canStopTurn={canStopTurn}
                  disabled={isThreadLoading}
                  error={composerError}
                  executionMode={executionMode}
                  isSending={isRuntimeBusy || isSending}
                  mentionItems={composerMentionItems}
                  onAddAttachments={handleAddAttachments}
                  onCapturePageArea={enablePageCapture ? handleCapturePageArea : undefined}
                  onChange={setComposer}
                  onReferenceAdd={handleReferenceAdd}
                  onReferenceRemove={handleReferenceRemove}
                  onSearchReferences={handleSearchReferences}
                  onSelectAgent={handleSelectAgent}
                  onSelectProvider={handleSelectProvider}
                  onRemoveAttachment={removeAttachment}
                  onStopTurn={handleStopTurn}
                  onSubmit={handleSend}
                  providers={providers}
                  queuedCount={queuedMessages.length}
                  queuedPreview={queuedMessages[0]?.content || null}
                  selectedAgentTypeId={composerSelectedAgentTypeId}
                  value={composer}
                />
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </main>
  );
}

function upsertOrderedThread(threads: ChatThread[], thread: ChatThread) {
  const nextThreads = threads.some((item) => item.thread_id === thread.thread_id)
    ? threads.map((item) => (item.thread_id === thread.thread_id ? { ...item, ...thread } : item))
    : [thread, ...threads];
  return orderChatThreads(nextThreads);
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

function referenceMentionItem(reference: AppReference): MentionItem {
  if (reference.type === "entity") {
    return {
      id: referenceKey(reference),
      label: reference.label || reference.entity_id,
      description: [reference.app_id, reference.entity_type, reference.summary].filter(Boolean).join(" · "),
      kind: "entity",
      reference,
    };
  }
  return {
    id: reference.app_id,
    label: reference.label || reference.app_id,
    description: "",
    kind: "app",
    reference,
  };
}

function mergeSelectedReferenceMentionItems(items: MentionItem[], selectedReferences: AppReference[]): MentionItem[] {
  const byKey = new Map<string, MentionItem>();
  for (const item of items) {
    byKey.set(item.reference ? referenceKey(item.reference) : `${item.kind}:${item.id}`, item);
  }
  for (const reference of selectedReferences) {
    byKey.set(referenceKey(reference), referenceMentionItem(reference));
  }
  return [...byKey.values()];
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
    .map(persistedAppReference)
    .filter((item) => (item.type === "app" ? Boolean(item.app_id) : Boolean(item.app_id && item.entity_type && item.entity_id)));
}

function persistedAppReference(item: Record<string, unknown>): AppReference {
  const appId = typeof item.app_id === "string" ? item.app_id : "";
  if (item.type === "entity") {
    return {
      type: "entity",
      app_id: appId,
      entity_type: typeof item.entity_type === "string" ? item.entity_type : "",
      entity_id: typeof item.entity_id === "string" ? item.entity_id : "",
      label: typeof item.label === "string" ? item.label : "",
      summary: typeof item.summary === "string" ? item.summary : undefined,
      deep_link: typeof item.deep_link === "string" ? item.deep_link : undefined,
      exists: typeof item.exists === "boolean" ? item.exists : undefined,
    };
  }
  return {
    type: "app",
    app_id: appId,
    label: typeof item.label === "string" ? item.label : undefined,
  };
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
