import type { CSSProperties, RefObject } from "react";
import type { AgentTypeSummary, AppReference, ChatMessage, ProviderItem } from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import type { MentionItem } from "../lib/mentions";
import { ChatComposer } from "./ChatComposer";
import type { ExecutionMode } from "./ChatComposer";
import { ChatTranscript } from "./ChatTranscript";

type ChatSurfaceProps = {
  activeProviderId: string;
  agentSelectorLocked: boolean;
  agents: AgentTypeSummary[];
  attachments: ComposerAttachment[];
  canStopTurn: boolean;
  chatMainStyle?: CSSProperties;
  composerError: string | null;
  composerMentionItems: MentionItem[];
  dockedComposerRef: RefObject<HTMLDivElement | null>;
  enablePageCapture: boolean;
  error: string | null;
  executionMode: ExecutionMode | null;
  isEmptyChatView: boolean;
  isSending: boolean;
  isThreadLoading: boolean;
  loadingLabel: string;
  mentionItems: MentionItem[];
  messages: ChatMessage[];
  onAddAttachments: (files: File[]) => void;
  onCapturePageArea: () => void;
  onChangeComposer: (value: string) => void;
  onReferenceAdd: (reference: AppReference) => void;
  onReferenceRemove: (reference: AppReference) => void;
  onRemoveAttachment: (id: string) => void;
  onSearchReferences: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  onSelectAgent: (agentTypeId: string) => void;
  onSelectProvider: (providerId: string) => void;
  onStopTurn: () => void;
  onSubmit: () => void;
  providers: ProviderItem[];
  queuedCount: number;
  queuedPreview: string | null;
  selectedAgentTypeId: string;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
  transcriptionContentTypes: string[];
  transcriptionMaxAudioBytes: number;
  transcriptionMaxDurationSeconds: number;
  transcriptionProviderAppId: string;
  transcriptionProviderAvailable: boolean;
  value: string;
};

export function ChatSurface({
  activeProviderId,
  agentSelectorLocked,
  agents,
  attachments,
  canStopTurn,
  chatMainStyle,
  composerError,
  composerMentionItems,
  dockedComposerRef,
  enablePageCapture,
  error,
  executionMode,
  isEmptyChatView,
  isSending,
  isThreadLoading,
  loadingLabel,
  mentionItems,
  messages,
  onAddAttachments,
  onCapturePageArea,
  onChangeComposer,
  onReferenceAdd,
  onReferenceRemove,
  onRemoveAttachment,
  onSearchReferences,
  onSelectAgent,
  onSelectProvider,
  onStopTurn,
  onSubmit,
  providers,
  queuedCount,
  queuedPreview,
  selectedAgentTypeId,
  speechMaxTextChars,
  speechProviderAppId,
  speechProviderAvailable,
  speechProviderQualityProfile,
  transcriptionContentTypes,
  transcriptionMaxAudioBytes,
  transcriptionMaxDurationSeconds,
  transcriptionProviderAppId,
  transcriptionProviderAvailable,
  value,
}: ChatSurfaceProps) {
  const composerProps = {
    activeProviderId,
    agentSelectorLocked,
    agents,
    attachments,
    canStopTurn,
    disabled: isThreadLoading,
    error: composerError,
    executionMode,
    isSending,
    mentionItems: composerMentionItems,
    onAddAttachments,
    onCapturePageArea: enablePageCapture ? onCapturePageArea : undefined,
    onChange: onChangeComposer,
    onReferenceAdd,
    onReferenceRemove,
    onSearchReferences,
    onSelectAgent,
    onSelectProvider,
    onRemoveAttachment,
    onStopTurn,
    onSubmit,
    providers,
    queuedCount,
    queuedPreview,
    selectedAgentTypeId,
    transcriptionProviderAppId,
    transcriptionProviderAvailable,
    transcriptionMaxAudioBytes,
    transcriptionMaxDurationSeconds,
    transcriptionContentTypes,
    value,
  };

  return (
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
              <ChatComposer {...composerProps} isEmptyMode />
            </div>
          ) : (
            <ChatTranscript
              error={error}
              isLoading={canStopTurn || isThreadLoading}
              loadingLabel={loadingLabel}
              mentionItems={mentionItems}
              messages={messages}
              speechMaxTextChars={speechMaxTextChars}
              speechProviderAvailable={speechProviderAvailable}
              speechProviderAppId={speechProviderAppId}
              speechProviderQualityProfile={speechProviderQualityProfile}
            />
          )}
          {!isEmptyChatView ? (
            <div className="chatapp-composer-dock" ref={dockedComposerRef}>
              <ChatComposer {...composerProps} />
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
