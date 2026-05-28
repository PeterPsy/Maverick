import { useCallback, useState } from "react";
import type { ChatThread, RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";
import type { ExternalFileDrop, ExternalMentionDrop } from "../lib/externalInputs";
import { type ActiveAppContext, loadWidgetActiveAppContext } from "../lib/activeAppContext";
import { postActiveThreadChanged } from "./chatActiveThreadNotifications";
import { useChatComposerContext } from "./useChatComposerContext";
import { useChatControllerPresentation } from "./useChatControllerPresentation";
import { useChatDependencies } from "./useChatDependencies";
import { useChatNavigation } from "./useChatNavigation";
import { useChatReadReceipts } from "./useChatReadReceipts";
import { useChatRuntimeControls } from "./useChatRuntimeControls";
import { useComposerAttachments } from "./useComposerAttachments";
import { DraftChat, useMessageSubmission } from "./useMessageSubmission";
import { useQueuedMessagePersistence } from "./useQueuedMessagePersistence";

type UseChatAppControllerParams = {
  enablePageCapture: boolean;
  externalFileDrop: ExternalFileDrop | null;
  externalMentionDrop: ExternalMentionDrop | null;
  navigationScope: string;
  newChatProjectId: string | null;
  newChatRequestId: string | null;
  runtimeThreads: ChatThread[] | null;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  threadId: string | null;
};

export function useChatAppController({
  enablePageCapture,
  externalFileDrop,
  externalMentionDrop,
  navigationScope,
  newChatProjectId,
  newChatRequestId,
  runtimeThreads,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  threadId,
}: UseChatAppControllerParams) {
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
    workspaceId,
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
  const hasExternalRuntimeThreads = Array.isArray(runtimeThreads);
  const canStopTurn = activeTurn?.status === "queued" || activeTurn?.status === "active";
  const isRuntimeBusy = canStopTurn;

  const { handleChatRootPointerDown } = useChatReadReceipts({
    activeThread,
    setActiveThread,
    setThreads,
  });
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
    workspaceId,
  });
  const { handleSelectAgent, handleSelectProvider, handleStopTurn, selectedAgentRuntimeConfig } = useChatRuntimeControls({
    activeThread,
    activeTurn,
    agentCatalogAppId,
    canStopTurn,
    selectedAgentTypeId,
    workspaceId,
    setActiveProviderId,
    setActiveTurn,
    setComposerError,
    setError,
    setEvents,
    setSelectedAgentTypeId,
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
  const { handleNavigationParams, handleUnavailableRuntimeSession } = useChatNavigation({
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
  const executionMode = activeSession?.effective_mode === "sandbox" || activeSession?.effective_mode === "full-access" ? activeSession.effective_mode : null;

  const loadInitialState = useCallback(async () => {
    setIsBootstrapping(true);
    try {
      const widgetActiveAppContext = await loadWidgetActiveAppContext();
      setActiveAppContext(widgetActiveAppContext);
      await loadInitialChatDependencies();
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat.");
    }
  }, [loadInitialChatDependencies]);

  const handleRuntimeSnapshot = useCallback(() => {
    setHasLoadedHistory(true);
    setIsHistoryLoading(false);
  }, []);

  function notifyActiveThreadChanged(activeThreadId: string) {
    postActiveThreadChanged({ activeThread, activeThreadId, navigationScope, threadId });
  }

  useQueuedMessagePersistence({ activeThread, isBootstrapping, navigationScope, queuedMessages });

  const presentation = useChatControllerPresentation({
    activeProviderId,
    activeThread,
    activeTurn,
    agentOptions,
    attachments,
    canStopTurn,
    composer,
    composerError,
    composerMentionItems,
    draftChat,
    enablePageCapture,
    error,
    events,
    executionMode,
    failedUserMessages,
    handleAddAttachments,
    handleCapturePageArea,
    handleChatRootPointerDown,
    handleReferenceAdd,
    handleReferenceRemove,
    handleSearchReferences,
    handleSelectAgent,
    handleSelectProvider,
    handleSend,
    handleStopTurn,
    hasLoadedHistory,
    isBootstrapping,
    isHistoryLoading,
    isRuntimeBusy,
    isSending,
    mentionItems,
    pendingUserMessages,
    providers,
    queuedMessages,
    removeAttachment,
    selectedAgentTypeId,
    setComposer,
    speechMaxTextChars,
    speechProviderAppId,
    speechProviderAvailable,
    speechProviderQualityProfile,
    transcriptionContentTypes,
    transcriptionMaxAudioBytes,
    transcriptionMaxDurationSeconds,
    transcriptionProviderAppId,
    transcriptionProviderAvailable,
  });

  return {
    loadInitialState,
    rootProps: presentation.rootProps,
    runtimeEvents: {
      activeTurn,
      onRuntimeSessionUnavailable: handleUnavailableRuntimeSession,
      onRuntimeSnapshot: handleRuntimeSnapshot,
      runtimeSessionId: activeThread?.runtime_session_id || null,
      setActiveSession,
      setActiveTurn,
      setError,
      setEvents,
      setPendingUserMessages,
    },
    shellMessages: {
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
    },
    surfaceProps: presentation.surfaceProps,
  };
}
