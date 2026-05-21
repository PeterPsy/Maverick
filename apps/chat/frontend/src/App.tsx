import { type CSSProperties, type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  ChatThread,
  getAgentDefinition,
  interruptRuntimeTurn,
  markThreadRead,
  previewAgentPrompt,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  selectProvider,
} from "./api/client";
import { ChatSurface } from "./components/ChatSurface";
import { useChatComposerContext } from "./hooks/useChatComposerContext";
import { useChatDependencies } from "./hooks/useChatDependencies";
import { useChatNavigation } from "./hooks/useChatNavigation";
import { useChatShellMessages } from "./hooks/useChatShellMessages";
import { useComposerAttachments } from "./hooks/useComposerAttachments";
import { AgentRuntimeConfig, DraftChat, useMessageSubmission } from "./hooks/useMessageSubmission";
import { useRuntimeEvents } from "./hooks/useRuntimeEvents";
import {
  ActiveAppContext,
  loadWidgetActiveAppContext,
  promptWithActiveAppContext,
} from "./lib/activeAppContext";
import { filesFromDataTransfer, hasFileDropData } from "./lib/fileDropAttachments";
import type { MentionItem } from "./lib/mentions";
import { persistQueuedMessages, queueStorageKey } from "./lib/queuedMessages";
import { mergeRuntimeEvents } from "./lib/runtimeEvents";
import { latestRuntimeStepLabel } from "./lib/runtimeStepLabels";
import { debugThreadSync } from "./lib/threadNavigation";
import { eventsToMessages } from "./lib/transcript";

export type ExternalMentionDrop = {
  items: MentionItem[];
  requestId: string;
};

export type ExternalFileDrop = {
  files: File[];
  requestId: string;
};

const MESSAGE_HISTORY_LIMIT = 50;

export function App({
  enablePageCapture = false,
  externalFileDrop = null,
  externalMentionDrop = null,
  navigationScope = "",
  newChatProjectId = null,
  newChatRequestId = null,
  runtimeThreads = null,
  runtimeThreadsError = null,
  runtimeThreadsLoaded = false,
  threadId = null,
}: {
  enablePageCapture?: boolean;
  externalFileDrop?: ExternalFileDrop | null;
  externalMentionDrop?: ExternalMentionDrop | null;
  navigationScope?: string;
  newChatProjectId?: string | null;
  newChatRequestId?: string | null;
  runtimeThreads?: ChatThread[] | null;
  runtimeThreadsError?: string | null;
  runtimeThreadsLoaded?: boolean;
  threadId?: string | null;
} = {}) {
  const {
    activeProviderId,
    agentCatalogAppId,
    agentOptions,
    loadAgentOptionsFromDependencies,
    loadAppDependencies,
    loadInitialChatDependencies,
    loadSpeechProviderFromDependencies,
    loadTranscriptionProviderFromDependencies,
    providers,
    selectedAgentTypeId,
    setActiveProviderId,
    setSelectedAgentTypeId,
    speechMaxTextChars,
    speechProviderAppId,
    speechProviderAvailable,
    speechProviderQualityProfile,
    transcriptionContentTypes,
    transcriptionMaxAudioBytes,
    transcriptionMaxDurationSeconds,
    transcriptionProviderAppId,
    transcriptionProviderAvailable,
  } = useChatDependencies();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [draftChat, setDraftChat] = useState<DraftChat | null>(null);
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [composer, setComposer] = useState("");
  const { addAttachments, attachments, clearAttachments, removeAttachment } = useComposerAttachments();
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [hasLoadedHistory, setHasLoadedHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [activeAppContext, setActiveAppContext] = useState<ActiveAppContext | null>(null);
  const hasHydratedQueuedMessagesRef = useRef(false);
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const dockedComposerRef = useRef<HTMLDivElement | null>(null);
  const [dockedComposerHeight, setDockedComposerHeight] = useState(144);
  const hasExternalRuntimeThreads = Array.isArray(runtimeThreads);
  const canStopTurn = activeTurn?.status === "queued" || activeTurn?.status === "active";
  const isRuntimeBusy = canStopTurn;
  const {
    composerMentionItems,
    handleAddAttachments,
    handleCapturePageArea,
    handleReferenceAdd,
    handleReferenceRemove,
    handleSearchReferences,
    mentionItems,
    setSelectedReferences,
  } = useChatComposerContext({
    activeAppContext,
    addAttachments,
    externalFileDrop,
    externalMentionDrop,
    navigationScope,
    setComposer,
    setComposerError,
  });
  const {
    failedUserMessages,
    handleSend,
    isSending,
    pendingUserMessages,
    queuedMessages,
    setFailedUserMessages,
    setPendingUserMessages,
    setQueuedMessages,
  } = useMessageSubmission({
    activeAppContext,
    activeThread,
    attachments,
    clearAttachments,
    composer,
    composerMentionItems,
    draftChat,
    isBootstrapping,
    isHistoryLoading,
    isRuntimeBusy,
    navigationScope,
    notifyActiveThreadChanged,
    selectedAgentRuntimeConfig,
    setActiveSession,
    setActiveThread,
    setActiveTurn,
    setComposer,
    setComposerError,
    setDraftChat,
    setError,
    setEvents,
    setSelectedReferences,
    setThreads,
    threads,
  });
  const { handleNavigationParams, handleSelectThread, handleUnavailableRuntimeSession } = useChatNavigation({
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
  });

  const messages = useMemo(() => {
    const currentMessages = eventsToMessages(events);
    const confirmedHumanMessageIds = new Set(currentMessages.filter((message) => message.role === "human").map((message) => message.id));
    const visibleMessages = [
      ...currentMessages,
      ...pendingUserMessages
        .filter((message) => !confirmedHumanMessageIds.has(message.clientMessageId))
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

  async function loadInitialState() {
    setIsBootstrapping(true);
    try {
      const widgetActiveAppContext = await loadWidgetActiveAppContext();
      setActiveAppContext(widgetActiveAppContext);
      await loadInitialChatDependencies();
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat.");
    }
  }

  useEffect(() => {
    loadInitialState();
  }, []);

  useChatShellMessages({
    addAttachments,
    agentCatalogAppId,
    loadAgentOptionsFromDependencies,
    loadAppDependencies,
    loadSpeechProviderFromDependencies,
    loadTranscriptionProviderFromDependencies,
    navigationScope,
    onNavigate: handleNavigationParams,
    setActiveAppContext,
    setComposerError,
    speechProviderAppId,
    transcriptionProviderAppId,
  });

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
      <ChatSurface
        activeProviderId={activeProviderId}
        agentSelectorLocked={Boolean(activeThread)}
        agents={agentOptions}
        attachments={attachments}
        canStopTurn={canStopTurn}
        chatMainStyle={chatMainStyle}
        composerError={composerError}
        composerMentionItems={composerMentionItems}
        dockedComposerRef={dockedComposerRef}
        enablePageCapture={enablePageCapture}
        error={error}
        executionMode={executionMode}
        isEmptyChatView={isEmptyChatView}
        isSending={isRuntimeBusy || isSending}
        isThreadLoading={isThreadLoading}
        loadingLabel={loadingLabel}
        mentionItems={mentionItems}
        messages={messages}
        onAddAttachments={handleAddAttachments}
        onCapturePageArea={handleCapturePageArea}
        onChangeComposer={setComposer}
        onReferenceAdd={handleReferenceAdd}
        onReferenceRemove={handleReferenceRemove}
        onRemoveAttachment={removeAttachment}
        onSearchReferences={handleSearchReferences}
        onSelectAgent={handleSelectAgent}
        onSelectProvider={handleSelectProvider}
        onStopTurn={handleStopTurn}
        onSubmit={handleSend}
        providers={providers}
        queuedCount={queuedMessages.length}
        queuedPreview={queuedMessages[0]?.content || null}
        selectedAgentTypeId={composerSelectedAgentTypeId}
        speechMaxTextChars={speechMaxTextChars}
        speechProviderAppId={speechProviderAppId}
        speechProviderAvailable={speechProviderAvailable}
        speechProviderQualityProfile={speechProviderQualityProfile}
        transcriptionContentTypes={transcriptionContentTypes}
        transcriptionMaxAudioBytes={transcriptionMaxAudioBytes}
        transcriptionMaxDurationSeconds={transcriptionMaxDurationSeconds}
        transcriptionProviderAppId={transcriptionProviderAppId}
        transcriptionProviderAvailable={transcriptionProviderAvailable}
        value={composer}
      />
    </main>
  );
}
