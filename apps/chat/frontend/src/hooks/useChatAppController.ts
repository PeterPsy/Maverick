import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getInterAgentRun,
  listInterAgentRunApprovals,
  listInterAgentRunEvents,
  listInterAgentRuns,
  resolveInterAgentApproval,
  type ChatThread,
  type InterAgentApprovalRecord,
  type InterAgentEventRecord,
  type InterAgentRunDetail,
  type MultiAgentComposerMode,
  type RuntimeEvent,
  type RuntimeSession,
  type RuntimeTurn,
} from "../api/client";
import type { ExternalFileDrop, ExternalMentionDrop } from "../lib/externalInputs";
import { type ActiveAppContext, loadWidgetActiveAppContext } from "../lib/activeAppContext";
import { providerUsesPlainHostedRuntime } from "../lib/providerRuntimeOptions";
import { openAppParamsInShell } from "../lib/shellNavigation";
import { postActiveThreadChanged } from "./chatActiveThreadNotifications";
import { useChatComposerContext } from "./useChatComposerContext";
import { useChatControllerPresentation } from "./useChatControllerPresentation";
import { useChatDependencies } from "./useChatDependencies";
import { useChatNavigation } from "./useChatNavigation";
import { useChatReadReceipts } from "./useChatReadReceipts";
import { useChatRuntimeControls } from "./useChatRuntimeControls";
import { useComposerAttachments } from "./useComposerAttachments";
import { DraftChat, conversationKeyFor, useMessageSubmission } from "./useMessageSubmission";
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

function isThreadAvailabilityBusy(availability: string) {
  return availability === "busy" || availability === "queued" || availability === "active";
}

function isRuntimeTurnBusy(turn: RuntimeTurn | null) {
  return turn?.status === "queued" || turn?.status === "active";
}

export function isActiveRuntimeTurnBusyForThread(activeTurn: RuntimeTurn | null, activeThread: ChatThread | null) {
  if (!isRuntimeTurnBusy(activeTurn)) {
    return false;
  }
  if (!activeThread) {
    return true;
  }
  return isThreadAvailabilityBusy(activeThread.availability);
}

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
    transcriptionChunkedDictationSupported,
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
  const selectedProvider = useMemo(() => {
    if (activeThread && activeSession?.runtime_mode === "plain_hosted_chat") {
      return (
        providers.find(
          (provider) =>
            provider.hosted_provider_id === activeSession.hosted_provider_id &&
            provider.hosted_model_id === activeSession.hosted_model_id,
        ) ||
        providers.find((provider) => provider.hosted_provider_id === activeSession.hosted_provider_id) ||
        null
      );
    }
    if (activeThread && activeSession?.provider_id) {
      return providers.find((provider) => provider.provider_id === activeSession.provider_id) || null;
    }
    return providers.find((provider) => provider.provider_id === activeProviderId) || null;
  }, [
    activeProviderId,
    activeSession?.hosted_model_id,
    activeSession?.hosted_provider_id,
    activeSession?.provider_id,
    activeSession?.runtime_mode,
    activeThread,
    providers,
  ]);
  const composerActiveProviderId = selectedProvider?.provider_id || activeProviderId;
  const allowedAttachmentInputModalities = useMemo(() => {
    const isHostedSession = activeThread
      ? activeSession?.runtime_mode === "plain_hosted_chat"
      : providerUsesPlainHostedRuntime(selectedProvider);
    if (!isHostedSession) {
      return null;
    }
    return selectedProvider?.input_modalities || [];
  }, [activeSession?.runtime_mode, activeThread, selectedProvider]);
  const { addAttachments, attachments, clearAttachments, removeAttachment } = useComposerAttachments({ allowedInputModalities: allowedAttachmentInputModalities });
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isOlderHistoryLoading, setIsOlderHistoryLoading] = useState(false);
  const [hasLoadedHistory, setHasLoadedHistory] = useState(false);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [olderHistoryRequestId, setOlderHistoryRequestId] = useState(0);
  const [visibleMessageLimit, setVisibleMessageLimit] = useState(50);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [activeAppContext, setActiveAppContext] = useState<ActiveAppContext | null>(null);
  const [multiAgentMode, setMultiAgentMode] = useState<MultiAgentComposerMode>("off");
  const [interAgentRuns, setInterAgentRuns] = useState<InterAgentRunDetail[]>([]);
  const [interAgentEventsByRunId, setInterAgentEventsByRunId] = useState<Record<string, InterAgentEventRecord[]>>({});
  const [interAgentApprovalsByRunId, setInterAgentApprovalsByRunId] = useState<Record<string, InterAgentApprovalRecord[]>>({});
  const [activeInterAgentGraphRunId, setActiveInterAgentGraphRunId] = useState<string | null>(null);
  const interAgentRefreshScopeRef = useRef("");
  const hasExternalRuntimeThreads = Array.isArray(runtimeThreads);
  const activeConversationKey = conversationKeyFor(activeThread, draftChat);
  const interAgentRefreshScope = `${activeThread?.runtime_session_id || ""}:${activeInterAgentGraphRunId || ""}`;
  interAgentRefreshScopeRef.current = interAgentRefreshScope;
  const runtimeCanStopTurn = isActiveRuntimeTurnBusyForThread(activeTurn, activeThread);
  const isRuntimeBusy = runtimeCanStopTurn;

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
  const runtimeControls = useChatRuntimeControls({
    activeThread,
    activeTurn,
    activeProviderId: composerActiveProviderId,
    agentCatalogAppId,
    canStopTurn: runtimeCanStopTurn,
    providers,
    selectedAgentTypeId,
    workspaceId,
    setActiveProviderId,
    setActiveTurn,
    setComposerError,
    setError,
    setEvents,
    setSelectedAgentTypeId,
  });
  const upsertInterAgentRunDetail = useCallback((detail: InterAgentRunDetail) => {
    setInterAgentRuns((current) => {
      const next = current.filter((item) => item.run.run_id !== detail.run.run_id);
      return [...next, detail].sort((left, right) => left.run.created_at.localeCompare(right.run.created_at));
    });
  }, []);
  const refreshInterAgentRuns = useCallback(async () => {
    const runtimeSessionId = activeThread?.runtime_session_id || "";
    const graphRunId = activeInterAgentGraphRunId || "";
    const refreshScope = `${runtimeSessionId}:${graphRunId}`;
    const isCurrentRefreshScope = () => interAgentRefreshScopeRef.current === refreshScope;
    if (!runtimeSessionId && !graphRunId) {
      if (isCurrentRefreshScope()) {
        setInterAgentRuns([]);
        setInterAgentEventsByRunId({});
        setInterAgentApprovalsByRunId({});
      }
      return;
    }
    try {
      let runDetails: InterAgentRunDetail[] = [];
      if (runtimeSessionId) {
        const payload = await listInterAgentRuns();
        runDetails = payload.items.filter((item) => item.run.root_runtime_session_id === runtimeSessionId);
        if (graphRunId && !runDetails.some((item) => item.run.run_id === graphRunId)) {
          const listedGraphRun = payload.items.find((item) => item.run.run_id === graphRunId);
          try {
            runDetails.push(listedGraphRun || (await getInterAgentRun(graphRunId)));
          } catch {
            // Leave the graph stub visible if the run cannot be loaded yet.
          }
        }
      } else if (graphRunId) {
        runDetails = [await getInterAgentRun(graphRunId)];
      }
      runDetails.sort((left, right) => left.run.created_at.localeCompare(right.run.created_at));
      if (!isCurrentRefreshScope()) {
        return;
      }
      setInterAgentRuns(runDetails);
      const [eventEntries, approvalEntries] = await Promise.all([
        Promise.all(
          runDetails.map(async (detail) => {
            try {
              const eventsPayload = await listInterAgentRunEvents(detail.run.run_id, { visibilityPlane: "summary", limit: 80 });
              return [detail.run.run_id, eventsPayload.items] as const;
            } catch {
              return [detail.run.run_id, []] as const;
            }
          }),
        ),
        Promise.all(
          runDetails.map(async (detail) => {
            try {
              const approvalsPayload = await listInterAgentRunApprovals(detail.run.run_id);
              return [detail.run.run_id, approvalsPayload.items] as const;
            } catch {
              return [detail.run.run_id, []] as const;
            }
          }),
        ),
      ]);
      if (!isCurrentRefreshScope()) {
        return;
      }
      setInterAgentEventsByRunId(Object.fromEntries(eventEntries));
      setInterAgentApprovalsByRunId(Object.fromEntries(approvalEntries));
    } catch {
      if (isCurrentRefreshScope()) {
        setInterAgentRuns([]);
        setInterAgentEventsByRunId({});
        setInterAgentApprovalsByRunId({});
      }
    }
  }, [activeInterAgentGraphRunId, activeThread?.runtime_session_id]);
  const handleResolveInterAgentApproval = useCallback(
    async (approvalId: string, approved: boolean) => {
      const response = await resolveInterAgentApproval(approvalId, { approved });
      setInterAgentApprovalsByRunId((current) => {
        const next = { ...current };
        for (const [runId, approvals] of Object.entries(next)) {
          next[runId] = approvals.map((approval) => (approval.approval_id === approvalId ? response.approval : approval));
        }
        return next;
      });
      await refreshInterAgentRuns();
    },
    [refreshInterAgentRuns],
  );
  const handleOpenInterAgentGraph = useCallback(
    (runId: string) => {
      setActiveInterAgentGraphRunId(runId);
      const opened = openAppParamsInShell(
        "chat",
        {
          app_page: `graph/${runId}`,
          thread_id: activeThread?.thread_id || "",
          inter_agent_run_id: runId,
        },
        { navigationScope },
      );
      if (!opened && typeof window !== "undefined") {
        const url = new URL(window.location.href);
        url.searchParams.set("view", "graph");
        url.searchParams.set("inter_agent_run_id", runId);
        window.history.pushState({}, "", url.toString());
      }
    },
    [activeThread?.thread_id, navigationScope],
  );
  const handleCloseInterAgentGraph = useCallback(() => {
    setActiveInterAgentGraphRunId(null);
    const opened = openAppParamsInShell(
      "chat",
      {
        thread_id: activeThread?.thread_id || "",
      },
      { navigationScope },
    );
    if (!opened && typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("view");
      url.searchParams.delete("inter_agent_run_id");
      window.history.pushState({}, "", url.toString());
    }
  }, [activeThread?.thread_id, navigationScope]);
  const {
    activeSubmissionTurnId,
    failedUserMessages,
    handleSend,
    isSending,
    pendingUserMessages,
    queuedMessages,
    setFailedUserMessages,
    setFailedUserMessagesForConversation,
    setPendingUserMessages,
    setPendingUserMessagesForConversation,
    setQueuedMessages,
    setQueuedMessagesForConversation,
    stopActiveSubmission,
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
    multiAgentMode,
    navigationScope,
    notifyActiveThreadChanged,
    onInterAgentRunChanged: upsertInterAgentRunDetail,
    selectedAgentRuntimeConfig: runtimeControls.selectedAgentRuntimeConfig,
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
  const canStopTurn = runtimeCanStopTurn || isSending || Boolean(activeSubmissionTurnId);
  const handleStopTurn = useCallback(async () => {
    if (await stopActiveSubmission()) {
      return;
    }
    await runtimeControls.handleStopTurn();
  }, [runtimeControls, stopActiveSubmission]);
  const { handleNavigationParams, handleUnavailableRuntimeSession } = useChatNavigation({
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
    setFailedUserMessagesForConversation,
    setHasLoadedHistory,
    setHasMoreHistory,
    setIsBootstrapping,
    setIsHistoryLoading,
    setIsOlderHistoryLoading,
    setPendingUserMessages,
    setPendingUserMessagesForConversation,
    setQueuedMessages,
    setQueuedMessagesForConversation,
    setSelectedReferences,
    setThreads,
    threadId,
    threads,
  });
  const executionMode = activeSession?.effective_mode === "sandbox" || activeSession?.effective_mode === "full-access" ? activeSession.effective_mode : null;

  useEffect(() => {
    setVisibleMessageLimit(50);
  }, [activeConversationKey]);

  useEffect(() => {
    void refreshInterAgentRuns();
  }, [refreshInterAgentRuns]);

  useEffect(() => {
    const hasActiveRun = interAgentRuns.some((detail) => !["completed", "failed", "cancelled"].includes(detail.run.status));
    if (!hasActiveRun) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refreshInterAgentRuns();
    }, 3000);
    return () => window.clearInterval(intervalId);
  }, [interAgentRuns, refreshInterAgentRuns]);

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

  const handleRevealOlderMessages = useCallback(() => {
    setVisibleMessageLimit((current) => current + 50);
  }, []);

  const handleLoadOlderHistory = useCallback(() => {
    if (!activeThread?.runtime_session_id || !hasMoreHistory || isOlderHistoryLoading) {
      return;
    }
    setIsOlderHistoryLoading(true);
    setOlderHistoryRequestId((current) => current + 1);
  }, [activeThread?.runtime_session_id, hasMoreHistory, isOlderHistoryLoading]);

  function notifyActiveThreadChanged(activeThreadId: string) {
    postActiveThreadChanged({ activeThread, activeThreadId, navigationScope, threadId });
  }

  useQueuedMessagePersistence({ activeConversationKey, isBootstrapping, navigationScope, queuedMessages });

  const presentation = useChatControllerPresentation({
    activeProviderId,
    activeConversationKey,
    activeInterAgentGraphRunId,
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
    handleOpenInterAgentGraph,
    handleResolveInterAgentApproval,
    handleSelectAgent: runtimeControls.handleSelectAgent,
    handleSelectProvider: runtimeControls.handleSelectProvider,
    handleSend,
    handleStopTurn,
    hasLoadedHistory,
    isBootstrapping,
    isHistoryLoading,
    isOlderHistoryLoading,
    isRuntimeBusy,
    isSending,
    interAgentApprovalsByRunId,
    interAgentEventsByRunId,
    interAgentRuns,
    mentionItems,
    onCloseInterAgentGraph: handleCloseInterAgentGraph,
    multiAgentMode,
    hasMoreHistory,
    onLoadOlderHistory: handleLoadOlderHistory,
    onRevealOlderMessages: handleRevealOlderMessages,
    pendingUserMessages,
    providers,
    providerSelectorLocked: Boolean(activeThread),
    queuedMessages,
    removeAttachment,
    selectedAgentTypeId,
    setMultiAgentMode,
    setComposer,
    speechMaxTextChars,
    speechProviderAppId,
    speechProviderAvailable,
    speechProviderQualityProfile,
    transcriptionContentTypes,
    transcriptionChunkedDictationSupported,
    transcriptionMaxAudioBytes,
    transcriptionMaxDurationSeconds,
    transcriptionProviderAppId,
    transcriptionProviderAvailable,
    visibleMessageLimit,
  });

  return {
    loadInitialState,
    rootProps: presentation.rootProps,
    runtimeEvents: {
      activeTurn,
      hasMoreHistory,
      onRuntimeSessionUnavailable: handleUnavailableRuntimeSession,
      onRuntimeSnapshot: handleRuntimeSnapshot,
      olderHistoryRequestId,
      runtimeSessionId: activeThread?.runtime_session_id || null,
      setActiveSession,
      setActiveTurn,
      setError,
      setEvents,
      setHasMoreHistory,
      setIsOlderHistoryLoading,
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
