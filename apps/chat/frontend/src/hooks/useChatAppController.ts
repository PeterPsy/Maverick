import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getInterAgentRun,
  listInterAgentRunApprovals,
  listInterAgentRunEvents,
  listInterAgentRuns,
  resolveInterAgentApproval,
  type ChatUsageSummary,
  type ChatThread,
  type InterAgentApprovalRecord,
  type InterAgentEventRecord,
  type InterAgentRunDetail,
  type MultiAgentComposerMode,
  type ProviderItem,
  type RuntimeEvent,
  type RuntimeSession,
  type RuntimeTurn,
} from "../api/client";
import type { ExternalFileDrop, ExternalMentionDrop } from "../lib/externalInputs";
import { type ActiveAppContext, loadWidgetActiveAppContext } from "../lib/activeAppContext";
import { composerRuntimeCapabilities } from "../lib/composerRuntimeCapabilities";
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
  return turn?.status === "queued" || turn?.status === "active" || turn?.status === "waiting_for_tool_confirmation";
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

export function runtimeAdmissionBlockMessage(session: RuntimeSession | null): string | null {
  if (session?.status === "recovery_required") {
    return "This chat is quarantined because its remote agentic state is ambiguous. Operator recovery or shutdown is required before another turn.";
  }
  if (session?.agentic_containment?.status === "NO-GO") {
    return "This chat is pinned to a remote agentic profile that is contained (NO-GO). Start a new chat with an available model.";
  }
  const status = session?.runtime_admission?.status;
  if (status === "provider_thread_missing") {
    return "This chat cannot continue because its provider conversation is no longer available. Start a new chat and hand off the prior transcript.";
  }
  if (status === "upgrade_required") {
    return "This chat cannot be upgraded automatically to the current runtime profile. Start a new chat and hand off the prior transcript.";
  }
  return null;
}

export function selectedProviderForSession({
  activeProviderId,
  activeSession,
  activeThread,
  providers,
}: {
  activeProviderId: string;
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  providers: ProviderItem[];
}): ProviderItem | null {
  const selectionSession = activeSession || runtimeSessionSummaryFromThread(activeThread);
  if (activeThread && selectionSession?.runtime_mode === "plain_hosted_chat") {
    const hostedProviderId = selectionSession.hosted_provider_id || "";
    const hostedModelId = selectionSession.hosted_model_id || "";
    const exact = providers.find((provider) => provider.hosted_provider_id === hostedProviderId && provider.hosted_model_id === hostedModelId);
    if (exact) {
      return exact;
    }
    const providerFallback = providers.find((provider) => provider.hosted_provider_id === hostedProviderId || provider.provider_id === hostedProviderId);
    if (providerFallback && hostedModelId) {
      return {
        ...providerFallback,
        provider_id: `hosted-session:${hostedProviderId}:${encodeURIComponent(hostedModelId)}`,
        hosted_provider_id: hostedProviderId,
        hosted_model_id: hostedModelId,
        default_model_family: hostedModelId,
        label: `${hostedModelId} - ${providerFallback.label || hostedProviderId}`,
      };
    }
    return providerFallback || null;
  }
  if (activeThread && selectionSession?.provider_id) {
    const pinnedBindingId = selectionSession.execution_binding?.workspace_binding_id || "";
    if (pinnedBindingId) {
      const pinned = providers.find((provider) => provider.workspace_profile_binding_id === pinnedBindingId);
      if (pinned) {
        return pinned;
      }
      const rolloutSkewProvider = providerById(
        providers,
        selectionSession.provider_id,
      );
      if (!selectionSession.agentic_governance && rolloutSkewProvider) {
        return rolloutSkewProvider;
      }
      return pinnedAgenticSessionProvider(selectionSession, pinnedBindingId);
    }
    return providerById(providers, selectionSession.provider_id) || existingThreadDefaultProvider(providers);
  }
  if (activeThread) {
    return existingThreadDefaultProvider(providers);
  }
  return providers.find((provider) => provider.provider_id === activeProviderId) || null;
}

function pinnedAgenticSessionProvider(
  session: RuntimeSession,
  pinnedBindingId: string,
): ProviderItem {
  const binding = session.execution_binding;
  const governance = session.agentic_governance;
  const contained = session.agentic_containment?.status === "NO-GO";
  const executionFamily = governance?.execution_family || (
    binding?.runtime_engine_id === "codex"
    && binding.adapter_id === "codex-app-server"
    && binding.model_provider_id === "codex"
    && binding.provider_protocol === "codex-app-server-stdio"
      ? "native_agent"
      : undefined
  );
  const modelId = governance?.model_id || binding?.model_id || "Pinned model";
  const destination = governance?.data_destination.display_label || "Pinned destination unavailable";
  const recipe = governance?.harness_recipe;
  return {
    provider_id: `${contained ? "contained" : "pinned"}-session:${encodeURIComponent(pinnedBindingId)}`,
    label: governance?.display_name || modelId,
    description: destination,
    kind: "runtime_backend",
    provider_role: "runtime_engine",
    status: contained ? "contained" : "pinned",
    selectable: false,
    unavailable_reason: contained
      ? governance?.containment.reason_code
        || session.agentic_containment?.reason_code
        || "remote_agentic_session_contained"
      : "Pinned to existing session",
    default_model_family: modelId,
    default_reasoning_effort: binding?.reasoning_effort || null,
    workspace_profile_binding_id: pinnedBindingId,
    execution_family: executionFamily,
    full_workspace_status: governance?.full_workspace_status,
    full_workspace_contract_revision: governance?.full_workspace_contract_revision || null,
    harness_recipe: recipe || null,
    provider_detail: `Provider: ${governance?.model_provider_id || binding?.model_provider_id || session.provider_id || "unavailable"} · Destination: ${destination}`,
    profile_detail: `Profile: ${governance?.profile_definition_id || binding?.profile_definition_id || "unavailable"}@${governance?.profile_definition_revision || binding?.profile_definition_revision || "unavailable"} · Recipe: ${recipe?.id || "unavailable"}@${recipe?.revision || "unavailable"} · Full Workspace: ${governance?.full_workspace_contract_revision || "unavailable"}`,
    agentic_containment_status: contained ? "NO-GO" : governance?.containment.status,
    agentic_containment_reason: contained
      ? governance?.containment.reason_code
        || session.agentic_containment?.reason_code
        || "remote_agentic_session_contained"
      : governance?.containment.reason_code || null,
    agentic_rollout_status: governance?.rollout_status || null,
    agentic_certificate_status: governance?.certificate_posture.effective_status || null,
    agentic_certificate_expires_at: governance?.certificate_posture.expires_at || null,
    agentic_egress_policy_id: governance?.egress_policy.policy_id || null,
    agentic_data_destination: governance?.data_destination || null,
    agentic_egress_policy: governance?.egress_policy || null,
    agentic_data_policy: governance?.data_policy || null,
    agentic_certificate_posture: governance?.certificate_posture || null,
    agentic_effective_capabilities: governance?.effective_capabilities || null,
  };
}

function runtimeSessionSummaryFromThread(thread: ChatThread | null): RuntimeSession | null {
  if (!thread?.runtime_session_id || !thread.runtime_mode) {
    return null;
  }
  return {
    session_id: thread.runtime_session_id,
    workspace_id: "",
    agent_id: thread.agent_label || "chat",
    status: "",
    effective_mode: "",
    runtime_mode: thread.runtime_mode,
    provider_id: thread.provider_id || undefined,
    hosted_provider_id: thread.hosted_provider_id || null,
    hosted_model_id: thread.hosted_model_id || null,
  };
}

function providerById(providers: ProviderItem[], providerId: string): ProviderItem | null {
  return providers.find((provider) => provider.provider_id === providerId) || null;
}

function existingThreadDefaultProvider(providers: ProviderItem[]): ProviderItem | null {
  return providerById(providers, "codex") || providers.find((provider) => provider.provider_role === "runtime_engine") || null;
}

export function providersForComposer(providers: ProviderItem[], selectedProvider: ProviderItem | null): ProviderItem[] {
  if (!selectedProvider || providers.some((provider) => provider.provider_id === selectedProvider.provider_id)) {
    return providers;
  }
  return [selectedProvider, ...providers];
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
    agentCatalogLoaded,
    agentCatalogLoading,
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
    speechProviderStreamingSupported,
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
  const [chatUsage, setChatUsage] = useState<ChatUsageSummary | null>(null);
  const [composer, setComposer] = useState("");
  const selectedProvider = useMemo(
    () => selectedProviderForSession({ activeProviderId, activeSession, activeThread, providers }),
    [activeProviderId, activeSession, activeThread, providers],
  );
  const composerActiveProviderId = selectedProvider?.provider_id || activeProviderId;
  const composerProviders = useMemo(() => providersForComposer(providers, selectedProvider), [providers, selectedProvider]);
  const composerCapabilities = useMemo(() => composerRuntimeCapabilities({
    activeSession,
    activeThread,
    selectedProvider,
  }), [activeSession, activeThread, selectedProvider]);
  const allowedAttachmentInputModalities = composerCapabilities.allowedAttachmentInputModalities;
  const { addAttachments, attachments, clearAttachments, removeAttachment } = useComposerAttachments({ allowedInputModalities: allowedAttachmentInputModalities });
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [initialDependenciesReady, setInitialDependenciesReady] = useState(false);
  const [targetConversationResolved, setTargetConversationResolved] = useState(false);
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
  const activeInterAgentRun = useMemo(() => {
    const runtimeSessionId = activeThread?.runtime_session_id || "";
    return [...interAgentRuns].reverse().find((detail) => (
      detail.run.root_runtime_session_id === runtimeSessionId
      && !["completed", "failed", "cancelled"].includes(detail.run.status)
    )) || null;
  }, [activeThread?.runtime_session_id, interAgentRuns]);
  const interAgentRefreshScopeRef = useRef("");
  const hasExternalRuntimeThreads = Array.isArray(runtimeThreads);
  const activeConversationKey = conversationKeyFor(activeThread, draftChat);
  const selectedAgent = agentOptions.find((agent) => agent.id === selectedAgentTypeId) || null;
  const skillMentionContext = useMemo(() => ({
    activationMode: activeThread
      ? activeSession?.skill_activation_mode
      : selectedAgent?.skill_activation_mode || (selectedAgent ? "implicit" : "explicit"),
    allowedSkillIds: activeThread ? activeSession?.skill_ids : selectedAgent?.skill_ids || [],
    provider: selectedProvider,
  }), [
    activeSession?.skill_activation_mode,
    activeSession?.skill_ids,
    activeThread,
    selectedAgent,
    selectedProvider,
  ]);
  const appReferencesAllowed = composerCapabilities.appReferencesAllowed;
  const interAgentRefreshScope = `${activeThread?.runtime_session_id || ""}:${activeInterAgentGraphRunId || ""}`;
  interAgentRefreshScopeRef.current = interAgentRefreshScope;
  const runtimeCanStopTurn = isActiveRuntimeTurnBusyForThread(activeTurn, activeThread);
  const isRuntimeBusy = runtimeCanStopTurn;

  useEffect(() => {
    setChatUsage(null);
  }, [activeThread?.runtime_session_id]);

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
    appReferencesAllowed,
    addAttachments,
    externalFileDrop,
    externalMentionDrop,
    navigationScope,
    skillMentionContext,
    setComposer,
    setComposerError,
    workspaceId,
  });
  const runtimeControls = useChatRuntimeControls({
    activeSession,
    activeThread,
    activeTurn,
    activeProviderId: composerActiveProviderId,
    agentCatalogAppId,
    canStopTurn: runtimeCanStopTurn,
    providers: composerProviders,
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
    activeInterAgentRun,
    activeAppContext: appReferencesAllowed ? activeAppContext : null,
    activeThread,
    activeTurn,
    attachments,
    canPreloadRuntime: initialDependenciesReady,
    clearAttachments,
    composer,
    composerMentionItems,
    draftChat,
    isBootstrapping: isBootstrapping || !initialDependenciesReady || !targetConversationResolved,
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
    setTargetConversationResolved,
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
    setInitialDependenciesReady(false);
    try {
      const widgetActiveAppContext = await loadWidgetActiveAppContext();
      setActiveAppContext(widgetActiveAppContext);
      await loadInitialChatDependencies();
      setInitialDependenciesReady(true);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat.");
      setInitialDependenciesReady(false);
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

  const composerReady = initialDependenciesReady && targetConversationResolved;

  useQueuedMessagePersistence({
    activeConversationKey,
    isBootstrapping: isBootstrapping || !composerReady,
    navigationScope,
    pendingUserMessages,
    queuedMessages,
  });

  const runtimeAdmissionError = runtimeAdmissionBlockMessage(activeSession);

  const presentation = useChatControllerPresentation({
    activeProviderId: composerActiveProviderId,
    activeConversationKey,
    activeInterAgentGraphRunId,
    activeThread,
    activeTurn,
    agentOptions,
    agentCatalogLoaded,
    agentCatalogLoading,
    composerReady,
    attachments,
    canStopTurn,
    composer,
    composerError: runtimeAdmissionError || composerError,
    runtimeAdmissionBlocked: Boolean(runtimeAdmissionError),
    composerMentionItems,
    chatUsage,
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
    handleReasoningEffortChange: runtimeControls.setReasoningEffort,
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
    providers: composerProviders,
    reasoningEffort: runtimeControls.reasoningEffort,
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
    speechProviderStreamingSupported,
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
      onUsageSnapshot: setChatUsage,
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
