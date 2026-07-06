import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage } from "../api/client";
import type { MentionItem } from "../lib/mentions";
import type { CopyMessageHandler } from "./MessageCopyButton";
import { MessageBubble } from "./MessageBubble";

export function MessageList({
  expandedMessages,
  latestToolMessageId,
  liveInterAgentRunIds,
  mentionItems,
  messages,
  onActiveSpeechMessageChange,
  onCopyMessage,
  onOpenInterAgentGraph,
  openedInterAgentGraphRunIds,
  onToggleExpanded,
  speakingMessageId,
  speechMaxTextChars,
  speechProviderAppId,
  speechProviderAvailable,
  speechProviderQualityProfile,
}: {
  expandedMessages: Set<string>;
  latestToolMessageId: string | null;
  liveInterAgentRunIds: ReadonlySet<string>;
  mentionItems: MentionItem[];
  messages: ChatMessage[];
  onActiveSpeechMessageChange: Dispatch<SetStateAction<string | null>>;
  onCopyMessage: CopyMessageHandler;
  onOpenInterAgentGraph?: (runId: string) => void;
  openedInterAgentGraphRunIds: ReadonlySet<string>;
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
          key={message.id}
          latestToolMessageId={latestToolMessageId}
          liveInterAgentRunIds={liveInterAgentRunIds}
          mentionItems={mentionItems}
          message={message}
          onActiveSpeechMessageChange={onActiveSpeechMessageChange}
          onCopyMessage={onCopyMessage}
          onOpenInterAgentGraph={onOpenInterAgentGraph}
          openedInterAgentGraphRunIds={openedInterAgentGraphRunIds}
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
