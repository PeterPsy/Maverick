import { useMemo } from "react";
import type {
  AgentTypeSummary,
  AppReference,
  ChatMessage,
  ChatThread,
  InterAgentApprovalRecord,
  InterAgentEventRecord,
  InterAgentRunDetail,
  MultiAgentComposerMode,
  ProviderItem,
  RuntimeEvent,
  RuntimeTurn,
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

const EVENT_PROJECTION_MIN_LIMIT = 500;
const EVENT_PROJECTION_EVENTS_PER_VISIBLE_MESSAGE = 80;

type UseChatControllerPresentationParams = {
  activeProviderId: string;
  activeConversationKey: string;
  activeInterAgentGraphRunId: string | null;
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  agentOptions: AgentTypeSummary[];
  attachments: ComposerAttachment[];
  canStopTurn: boolean;
  composer: string;
  composerError: string | null;
  composerMentionItems: MentionItem[];
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
  handleResolveInterAgentApproval: (approvalId: string, approved: boolean) => Promise<void>;
  handleSelectAgent: (agentTypeId: string) => void;
  handleSelectProvider: (providerId: string) => void;
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
  queuedMessages: QueuedMessage[];
  removeAttachment: (attachmentId: string) => void;
  hasMoreHistory: boolean;
  onLoadOlderHistory: () => void;
  onRevealOlderMessages: () => void;
  selectedAgentTypeId: string;
  setMultiAgentMode: (mode: MultiAgentComposerMode) => void;
  setComposer: (value: string) => void;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
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
  handleSelectAgent,
  handleSelectProvider,
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
  queuedMessages,
  removeAttachment,
  hasMoreHistory,
  onLoadOlderHistory,
  onRevealOlderMessages,
  selectedAgentTypeId,
  setMultiAgentMode,
  setComposer,
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
    !isBootstrapping &&
    !isHistoryLoading &&
    !isTranscriptHistoryPending &&
    !error;
  const isThreadLoading = isBootstrapping || isHistoryLoading || isTranscriptHistoryPending;
  const { chatMainStyle, dockedComposerRef } = useDockedComposerHeight({
    attachmentCount: attachments.length,
    composerError,
    isEmptyChatView,
    queuedMessageCount: queuedMessages.length,
  });
  const loadingLabel = useMemo(
    () =>
      runtimeActivityLabel({
        activeTurn,
        events,
        isBootstrapping,
        isHistoryLoading,
        isRuntimeBusy,
        isSending,
      }),
    [activeTurn, events, isBootstrapping, isHistoryLoading, isRuntimeBusy, isSending],
  );
  const multiAgentBudgetLabel = useMemo(() => {
    if (multiAgentMode === "multi") {
      return "2 participants · 4 turns · 4 tool calls";
    }
    if (multiAgentMode === "auto") {
      return "2 participants · 2 turns · 1 tool call";
    }
    return "";
  }, [multiAgentMode]);
  const { handleChatRootDragOver, handleChatRootDrop } = useChatRootDropHandlers({
    disabled: isThreadLoading,
    handleAddAttachments,
  });
  const surfaceProps: ChatSurfaceProps = {
    composerProps: {
      activeProviderId,
      agentSelectorLocked: Boolean(activeThread),
      agents: agentOptions,
      attachments,
      canStopTurn,
      disabled: isThreadLoading,
      error: composerError,
      executionMode,
      isSending: isRuntimeBusy || isSending,
      mentionItems: composerMentionItems,
      multiAgentBudgetLabel,
      multiAgentMode,
      onAddAttachments: handleAddAttachments,
      onCapturePageArea: enablePageCapture ? handleCapturePageArea : undefined,
      onChange: setComposer,
      onReferenceAdd: handleReferenceAdd,
      onReferenceRemove: handleReferenceRemove,
      onRemoveAttachment: removeAttachment,
      onSearchReferences: handleSearchReferences,
      onSelectMultiAgentMode: setMultiAgentMode,
      onSelectAgent: handleSelectAgent,
      onSelectProvider: handleSelectProvider,
      onStopTurn: handleStopTurn,
      onSubmit: handleSend,
      providers,
      queuedCount: queuedMessages.length,
      queuedPreview: queuedMessages[0]?.content || null,
      selectedAgentTypeId: composerSelectedAgentTypeId,
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
    const projectedEvents = visibleProjectionEvents(events, messageHistoryLimit);
    const currentMessages = eventsToMessages(projectedEvents);
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
    const messages = visibleMessages.slice(-messageHistoryLimit);
    return { hasHiddenMessages: projectedEvents.length < events.length || visibleMessages.length > messages.length, messages };
  }, [events, failedUserMessages, messageHistoryLimit, pendingUserMessages]);
}

function visibleProjectionEvents(events: RuntimeEvent[], messageHistoryLimit: number): RuntimeEvent[] {
  const eventLimit = Math.max(EVENT_PROJECTION_MIN_LIMIT, messageHistoryLimit * EVENT_PROJECTION_EVENTS_PER_VISIBLE_MESSAGE);
  return events.length > eventLimit ? events.slice(-eventLimit) : events;
}
