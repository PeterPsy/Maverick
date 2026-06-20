import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage } from "../api/client";
import type { MentionItem } from "../lib/mentions";
import { MessageBubble } from "./MessageBubble";

export function MessageList({
  expandedMessages,
  interAgentRunStatusById,
  latestToolMessageId,
  mentionItems,
  messages,
  onActiveSpeechMessageChange,
  onCopyMessage,
  onOpenInterAgentGraph,
  onToggleExpanded,
  speakingMessageId,
  speechMaxTextChars,
  speechProviderAppId,
  speechProviderAvailable,
  speechProviderQualityProfile,
}: {
  expandedMessages: Set<string>;
  interAgentRunStatusById?: Record<string, string>;
  latestToolMessageId: string | null;
  mentionItems: MentionItem[];
  messages: ChatMessage[];
  onActiveSpeechMessageChange: Dispatch<SetStateAction<string | null>>;
  onCopyMessage: (content: string) => Promise<void>;
  onOpenInterAgentGraph?: (runId: string) => void;
  onToggleExpanded: (messageId: string) => void;
  speakingMessageId: string | null;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
}) {
  return (
    <>
      {messages.map((message) => (
        <MessageBubble
          expanded={expandedMessages.has(message.id)}
          interAgentRunStatusById={interAgentRunStatusById}
          key={message.id}
          latestToolMessageId={latestToolMessageId}
          mentionItems={mentionItems}
          message={message}
          onActiveSpeechMessageChange={onActiveSpeechMessageChange}
          onCopyMessage={onCopyMessage}
          onOpenInterAgentGraph={onOpenInterAgentGraph}
          onToggleExpanded={onToggleExpanded}
          speakingMessageId={speakingMessageId}
          speechMaxTextChars={speechMaxTextChars}
          speechProviderAppId={speechProviderAppId}
          speechProviderAvailable={speechProviderAvailable}
          speechProviderQualityProfile={speechProviderQualityProfile}
        />
      ))}
    </>
  );
}
