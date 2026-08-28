import { useMemo } from "react";
import type {
  AgentTypeSummary,
  AppReference,
  ChatMessage,
  ChatThread,
  ChatUsageSummary,
  InterAgentApprovalRecord,
  InterAgentEventRecord,
  InterAgentRunDetail,
  MultiAgentComposerMode,
  ProviderItem,
  RuntimeEvent,
  RuntimeTurn,
  SourceAppChatMode,
} from "../api/client";
import type { ChatSurfaceProps } from "../components/ChatSurface";
import type { ExecutionMode } from "../components/ChatComposer";
import type { ComposerAttachment } from "../lib/attachments";
import type { MentionItem } from "../lib/mentions";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { runtimeActivityLabel } from "../lib/runtimeActivity";
import { eventsToMessages } from "../lib/transcript";
import { useChatRootDropHandlers } from "./useChatRootDropHandlers";
import { useDockedComposerHeight } from "./useDockedComposerHeight";
import type { DraftChat } from "./useMessageSubmission";
import { interAgentComposerBudgetLabel } from "./useMessageSubmission";

const EVENT_PROJECTION_MIN_LIMIT = 500;
const EVENT_PROJECTION_EVENTS_PER_VISIBLE_MESSAGE = 80;

type UseChatControllerPresentationParams = {
  activeProviderId: string;
  activeConversationKey: string;
  activeInterAgentGraphRunId: string | null;
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  agentCatalogLoaded: boolean;
  agentCatalogLoading: boolean;
  agentOptions: AgentTypeSummary[];
  composerReady: boolean;
  attachments: ComposerAttachment[];
  canStopTurn: boolean;
  composer: string;
  composerError: string | null;
  runtimeAdmissionBlocked: boolean;
  composerMentionItems: MentionItem[];
  chatUsage: ChatUsageSummary | null;
  draftChat: DraftChat | null;
  enablePageCapture: boolean;
  error: string | null;
  events: RuntimeEvent[];
  executionMode: ExecutionMode | null;
  failedUserMessages: PendingMessage[];
  handleAddAttachments: (files: File[]) => void;
  handleCapturePageArea: () => void;
  handleChatRootPointerDown: () => void;
  handleReferenceAdd: (reference: AppReference) => void;
  handleReferenceRemove: (reference: AppReference) => void;
  handleSearchReferences: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  handleOpenInterAgentGraph: (runId: string) => void;
  handleOpenSourceAppSettings: (section?: "designSystems") => void;
  handleOpenSourceAppTools: () => void;
  handleResolveSourceAppProject: (projectId: string) => void;
  handleResolveInterAgentApproval: (approvalId: string, approved: boolean) => Promise<void>;
  handleSelectAgent: (agentTypeId: string) => void;
  handleSelectSourceAppProject: (projectId: string) => void;
  handleSelectProvider: (providerId: string) => void;
  handleReasoningEffortChange: (effort: string) => void;
  handleSend: () => void;
  handleStopTurn: () => void;
  hasLoadedHistory: boolean;
  isBootstrapping: boolean;
  isHistoryLoading: boolean;
  isOlderHistoryLoading: boolean;
  isRuntimeBusy: boolean;
  isSending: boolean;
  interAgentApprovalsByRunId: Record<string, InterAgentApprovalRecord[]>;
  interAgentEventsByRunId: Record<string, InterAgentEventRecord[]>;
  interAgentRuns: InterAgentRunDetail[];
  mentionItems: MentionItem[];
  multiAgentMode: MultiAgentComposerMode;
  onCloseInterAgentGraph: () => void;
  pendingUserMessages: PendingMessage[];
  providers: ProviderItem[];
  reasoningEffort: string;
  providerSelectorLocked: boolean;
  queuedMessages: QueuedMessage[];
  removeAttachment: (attachmentId: string) => void;
  hasMoreHistory: boolean;
  onLoadOlderHistory: () => void;
  onRevealOlderMessages: () => void;
  selectedAgentTypeId: string;
  sourceAppChatMode: SourceAppChatMode;
  sourceAppId: string;
  sourceAppProjectId: string;
  sourceAppProjectSelectionLocked: boolean;
  setSourceAppChatMode: (mode: SourceAppChatMode) => void;
  setMultiAgentMode: (mode: MultiAgentComposerMode) => void;
  setComposer: (value: string) => void;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
  speechProviderStreamingSupported: boolean;
  transcriptionChunkedDictationSupported: boolean;
  transcriptionContentTypes: string[];
  transcriptionMaxAudioBytes: number;
  transcriptionMaxDurationSeconds: number;
  transcriptionProviderAppId: string;
  transcriptionProviderAvailable: boolean;
  visibleMessageLimit: number;
};

export function useChatControllerPresentation({
  activeProviderId,
  activeConversationKey,
  activeInterAgentGraphRunId,
  activeThread,
  activeTurn,
  agentCatalogLoaded,
  agentCatalogLoading,
  agentOptions,
  composerReady,
  attachments,
  canStopTurn,
  composer,
  composerError,
  runtimeAdmissionBlocked,
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
  handleOpenSourceAppSettings,
  handleOpenSourceAppTools,
  handleResolveSourceAppProject,
  handleResolveInterAgentApproval,
  handleSelectAgent,
  handleSelectSourceAppProject,
  handleSelectProvider,
  handleReasoningEffortChange,
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
  multiAgentMode,
  onCloseInterAgentGraph,
  pendingUserMessages,
  providers,
  reasoningEffort,
  providerSelectorLocked,
  queuedMessages,
  removeAttachment,
  hasMoreHistory,
  onLoadOlderHistory,
  onRevealOlderMessages,
  selectedAgentTypeId,
  sourceAppChatMode,
  sourceAppId,
  sourceAppProjectId,
  sourceAppProjectSelectionLocked,
  setSourceAppChatMode,
  setMultiAgentMode,
  setComposer,
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
  visibleMessageLimit,
}: UseChatControllerPresentationParams) {
  const { hasHiddenMessages, messages } = useVisibleChatMessages(events, pendingUserMessages, failedUserMessages, visibleMessageLimit);
  const composerSelectedAgentTypeId = activeThread
    ? activeThread.source_app_id && activeThread.source_app_id !== "chat"
      ? activeThread.agent_type_id
      : ""
    : selectedAgentTypeId;
  const isTranscriptHistoryPending = Boolean(activeThread?.runtime_session_id && !hasLoadedHistory && messages.length === 0);
  const isEmptyChatView =
    Boolean(draftChat) &&
    messages.length === 0 &&
    !isRuntimeBusy &&
    !isSending &&
    composerReady &&
    !isHistoryLoading &&
    !isTranscriptHistoryPending &&
    !error;
  const isThreadLoading = !composerReady || isHistoryLoading || isTranscriptHistoryPending;
  const { chatMainStyle, dockedComposerHeight, dockedComposerRef } = useDockedComposerHeight({
    attachmentCount: attachments.length,
    composerError,
    isComposerDockVisible: !activeInterAgentGraphRunId,
    isEmptyChatView,
    queuedMessageCount: queuedMessages.length,
  });
  const isCriticalBootstrapping = isBootstrapping && !composerReady;
  const loadingLabel = useMemo(
    () =>
      runtimeActivityLabel({
        activeTurn,
        events,
        isBootstrapping: isCriticalBootstrapping,
        isHistoryLoading,
        isRuntimeBusy,
        isSending,
      }),
    [activeTurn, events, isCriticalBootstrapping, isHistoryLoading, isRuntimeBusy, isSending],
  );
  const multiAgentBudgetLabel = useMemo(() => {
    return interAgentComposerBudgetLabel(multiAgentMode);
  }, [multiAgentMode]);
  const { handleChatRootDragOver, handleChatRootDrop } = useChatRootDropHandlers({
    disabled: isThreadLoading || runtimeAdmissionBlocked,
    handleAddAttachments,
  });
  const surfaceProps: ChatSurfaceProps = {
    composerProps: {
      activeProviderId,
      agentCatalogLoading: agentCatalogLoading && !agentCatalogLoaded,
      agentSelectorLocked: Boolean(activeThread),
      agents: agentOptions,
      attachments,
      canStopTurn,
      disabled: isThreadLoading || runtimeAdmissionBlocked,
      error: composerError,
      executionMode,
      isSending,
      mentionItems: composerMentionItems,
      usage: chatUsage,
      multiAgentBudgetLabel,
      multiAgentMode,
      onAddAttachments: handleAddAttachments,
      onCapturePageArea: enablePageCapture ? handleCapturePageArea : undefined,
      onChange: setComposer,
      onReferenceAdd: handleReferenceAdd,
      onReferenceRemove: handleReferenceRemove,
      onRemoveAttachment: removeAttachment,
      onOpenSourceAppSettings: handleOpenSourceAppSettings,
      onOpenSourceAppTools: handleOpenSourceAppTools,
      onResolveSourceAppProject: handleResolveSourceAppProject,
      onSearchReferences: handleSearchReferences,
      onSelectMultiAgentMode: setMultiAgentMode,
      onSelectAgent: handleSelectAgent,
      onSelectProvider: handleSelectProvider,
      onSelectSourceAppProject: handleSelectSourceAppProject,
      onReasoningEffortChange: handleReasoningEffortChange,
      onStopTurn: handleStopTurn,
      onSubmit: handleSend,
      providers,
      reasoningEffort,
      providerSelectorLocked,
      queuedCount: queuedMessages.length,
      queuedPreview: queuedMessages[0]?.content || null,
      selectedAgentTypeId: composerSelectedAgentTypeId,
      sourceAppChatMode,
      sourceAppId,
      sourceAppProjectId,
      sourceAppProjectSelectionLocked,
      onSelectSourceAppChatMode: setSourceAppChatMode,
      transcriptionChunkedDictationSupported,
      transcriptionContentTypes,
      transcriptionMaxAudioBytes,
      transcriptionMaxDurationSeconds,
      transcriptionProviderAppId,
      transcriptionProviderAvailable,
      value: composer,
    },
    surfaceActions: {
      dockedComposerRef,
    },
    surfaceState: {
      chatMainStyle,
      isEmptyChatView,
    },
    transcriptProps: {
      error,
      hasMoreOlderMessages: hasHiddenMessages || hasMoreHistory,
      activeInterAgentGraphRunId,
      composerOverlayHeight: dockedComposerHeight,
      conversationKey: activeConversationKey,
      isLoading: canStopTurn || isThreadLoading,
      isLoadingOlderHistory: isOlderHistoryLoading,
      interAgentApprovalsByRunId,
      interAgentEventsByRunId,
      interAgentRuns,
      loadingLabel,
      mentionItems,
      messages,
      onCloseInterAgentGraph,
      onOpenInterAgentGraph: handleOpenInterAgentGraph,
      onResolveInterAgentApproval: handleResolveInterAgentApproval,
      onLoadOlderMessages: hasHiddenMessages ? onRevealOlderMessages : onLoadOlderHistory,
      speechMaxTextChars,
      speechProviderAppId,
      speechProviderAvailable,
      speechProviderQualityProfile,
      speechProviderStreamingSupported,
    },
  };

  return {
    rootProps: {
      onDragOver: handleChatRootDragOver,
      onDrop: handleChatRootDrop,
      onPointerDown: handleChatRootPointerDown,
    },
    surfaceProps,
  };
}

function useVisibleChatMessages(
  events: RuntimeEvent[],
  pendingUserMessages: PendingMessage[],
  failedUserMessages: PendingMessage[],
  messageHistoryLimit: number,
): { hasHiddenMessages: boolean; messages: ChatMessage[] } {
  return useMemo(() => {
    return visibleChatMessages(events, pendingUserMessages, failedUserMessages, messageHistoryLimit);
  }, [events, failedUserMessages, messageHistoryLimit, pendingUserMessages]);
}

export function visibleChatMessages(
  events: RuntimeEvent[],
  pendingUserMessages: PendingMessage[],
  failedUserMessages: PendingMessage[],
  messageHistoryLimit: number,
): { hasHiddenMessages: boolean; messages: ChatMessage[] } {
  const projectedEvents = visibleProjectionEvents(events, messageHistoryLimit);
  const currentMessages = eventsToMessages(projectedEvents);
  const confirmedHumanMessageIds = confirmedHumanMessageIdsForEvents(events, currentMessages);
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
  const messages = visibleMessages.slice(-messageHistoryLimit);
  return { hasHiddenMessages: projectedEvents.length < events.length || visibleMessages.length > messages.length, messages };
}

export function visibleProjectionEvents(events: RuntimeEvent[], messageHistoryLimit: number): RuntimeEvent[] {
  const eventLimit = Math.max(EVENT_PROJECTION_MIN_LIMIT, messageHistoryLimit * EVENT_PROJECTION_EVENTS_PER_VISIBLE_MESSAGE);
  if (events.length <= eventLimit) {
    return events;
  }
  const initialStartIndex = events.length - eventLimit;
  return events.slice(turnBoundaryStartIndex(events, initialStartIndex));
}

function confirmedHumanMessageIdsForEvents(events: RuntimeEvent[], currentMessages: ChatMessage[]): Set<string> {
  const ids = new Set(currentMessages.filter((message) => message.role === "human").map((message) => message.id));
  for (const event of events) {
    if (event.event_type !== "runtime.turn.queued") {
      continue;
    }
    const clientMessageId = event.payload.client_message_id;
    if (typeof clientMessageId === "string" && clientMessageId) {
      ids.add(clientMessageId);
    }
  }
  return ids;
}

function turnBoundaryStartIndex(events: RuntimeEvent[], initialStartIndex: number): number {
  const includedTurnIds = new Set<string>();
  for (let index = initialStartIndex; index < events.length; index += 1) {
    const turnId = events[index].turn_id;
    if (turnId) {
      includedTurnIds.add(turnId);
    }
  }
  if (!includedTurnIds.size) {
    return initialStartIndex;
  }
  for (let index = 0; index < initialStartIndex; index += 1) {
    const turnId = events[index].turn_id;
    if (turnId && includedTurnIds.has(turnId)) {
      return index;
    }
  }
  return initialStartIndex;
}
