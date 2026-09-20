import { memo, type Dispatch, type SetStateAction, type RefObject } from "react";
import type { ChatMessage } from "../api/client";
import type { InterAgentBoardLink } from "../lib/interAgentTranscript";
import type { MentionItem } from "../lib/mentions";
import type { CopyMessageHandler } from "./MessageCopyButton";
import { MessageBubble } from "./MessageBubble";
import { useTranscriptWindow } from '../hooks/useTranscriptWindow';

const StableMessageBubble = memo(MessageBubble);

export function MessageList({
  expandedMessages,
  interAgentBoardLinksByMessageId = {},
  latestToolMessageId,
  mentionItems,
  messages,
  onActiveSpeechMessageChange,
  onCopyMessage,
  onContinueFromProviderOverload,
  onOpenInterAgentGraph,
  onToggleExpanded,
  speakingMessageId,
  speechMaxTextChars,
  speechProviderAppId,
  speechProviderAvailable,
  speechProviderQualityProfile,
  speechProviderStreamingSupported,
  viewportRef,
}: {
  expandedMessages: Set<string>;
  interAgentBoardLinksByMessageId?: Record<string, InterAgentBoardLink>;
  latestToolMessageId: string | null;
  mentionItems: MentionItem[];
  messages: ChatMessage[];
  onActiveSpeechMessageChange: Dispatch<SetStateAction<string | null>>;
  onCopyMessage: CopyMessageHandler;
  onContinueFromProviderOverload?: () => void;
  onOpenInterAgentGraph?: (runId: string) => void;
  onToggleExpanded: (messageId: string) => void;
  speakingMessageId: string | null;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
  speechProviderStreamingSupported: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
}) {
  const windowed = useTranscriptWindow(messages, viewportRef, speakingMessageId);
  const latestMessage = messages.at(-1);
  const recoverableFailureMessageId =
    latestMessage?.role === "system" &&
    latestMessage.failureReasonCode === "provider_overloaded"
      ? latestMessage.id
      : null;

  return (
    <div className="chatapp-message-list" ref={windowed.container} style={windowed.enabled ? { overflowAnchor: 'none' } : undefined}>
      {windowed.before > 0 ? <div aria-hidden="true" style={{ height: windowed.before }} /> : null}
      {windowed.rows.map((message) => (
        <div key={message.id} data-transcript-row={message.id} hidden={windowed.hiddenRowId === message.id}>
        <StableMessageBubble
          expanded={expandedMessages.has(message.id)}
          interAgentBoardLink={interAgentBoardLinksByMessageId[message.id]}
          key={message.id}
          latestToolMessageId={latestToolMessageId}
          mentionItems={mentionItems}
          message={message}
          onActiveSpeechMessageChange={onActiveSpeechMessageChange}
          onCopyMessage={onCopyMessage}
          onContinueFromProviderOverload={
            message.id === recoverableFailureMessageId
              ? onContinueFromProviderOverload
              : undefined
          }
          onOpenInterAgentGraph={onOpenInterAgentGraph}
          onToggleExpanded={onToggleExpanded}
          speakingMessageId={speakingMessageId}
          speechMaxTextChars={speechMaxTextChars}
          speechProviderAppId={speechProviderAppId}
          speechProviderAvailable={speechProviderAvailable}
          speechProviderQualityProfile={speechProviderQualityProfile}
          speechProviderStreamingSupported={speechProviderStreamingSupported}
        />
        </div>
      ))}
      {windowed.after > 0 ? <div aria-hidden="true" style={{ height: windowed.after }} /> : null}
    </div>
  );
}
