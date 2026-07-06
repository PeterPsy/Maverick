import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage } from "../api/client";
import type { InterAgentBoardLink } from "../lib/interAgentTranscript";
import type { MentionItem } from "../lib/mentions";
import { HumanMessage } from "./HumanMessage";
import { InterAgentBoardButton } from "./InterAgentBoardButton";
import { MarkdownMessage } from "./MarkdownMessage";
import { CopyMessageButton, type CopyMessageHandler } from "./MessageCopyButton";
import { MessageFooter, formatMessageTime } from "./MessageFooter";
import { MessageSpeechButton } from "./MessageSpeechButton";
import { RuntimeStepMessage } from "./RuntimeStepMessage";
import { StructuredContentMessage } from "./StructuredContentMessage";
import { ToolCallInlineMessage } from "./ToolCallInlineMessage";

export function MessageBubble({
  expanded,
  interAgentBoardLink,
  latestToolMessageId,
  mentionItems,
  message,
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
  expanded: boolean;
  interAgentBoardLink?: InterAgentBoardLink;
  latestToolMessageId: string | null;
  mentionItems: MentionItem[];
  message: ChatMessage;
  onActiveSpeechMessageChange: Dispatch<SetStateAction<string | null>>;
  onCopyMessage: CopyMessageHandler;
  onOpenInterAgentGraph?: (runId: string) => void;
  onToggleExpanded: (messageId: string) => void;
  speakingMessageId: string | null;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
}) {
  const shouldCollapse = message.role === "agent" && message.content.length > 3200 && !expanded;
  const visibleContent = shouldCollapse ? `${message.content.slice(0, 3200)}\n\n...` : message.content;
  const hasMobileFooter = message.role === "human" || message.role === "agent";
  const toolCalls = message.role === "tool" ? (message.toolCalls?.length ? message.toolCalls : message.toolCall ? [message.toolCall] : []) : [];
  const isToolMessage = toolCalls.length > 0;

  return (
    <article
      className={`chatapp-bubble ${bubbleClass(message)} ${message.status === "failed" ? "is-error" : ""} ${
        hasMobileFooter ? "has-mobile-message-footer" : ""
      }`}
    >
      {message.role === "human" ? (
        <HumanMessage message={message} mentionItems={mentionItems} onCopyMessage={onCopyMessage} />
      ) : message.role === "system" ? (
        <div className={`chatapp-system-update ${message.status === "failed" ? "chatapp-system-update--error" : ""}`}>
          <span className="chatapp-system-update__icon" aria-hidden="true">
            <span className="material-symbols-rounded">{message.status === "failed" ? "error" : "info"}</span>
          </span>
          <span className="chatapp-system-update__label">{message.content}</span>
        </div>
      ) : isToolMessage ? (
        <ToolCallInlineMessage createdAt={message.createdAt} defaultExpanded={message.id === latestToolMessageId} toolCalls={toolCalls} />
      ) : message.role === "step" && message.step ? (
        <RuntimeStepMessage step={message.step} />
      ) : message.role === "structured" && message.structuredContent ? (
        <StructuredContentMessage content={message.structuredContent} messageId={message.id} />
      ) : (
        <AgentMessage
          expanded={expanded}
          interAgentBoardLink={interAgentBoardLink}
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
          visibleContent={visibleContent}
        />
      )}
      {isToolMessage ? null : <MessageMeta message={message} onCopyMessage={onCopyMessage} />}
    </article>
  );
}

function AgentMessage({
  expanded,
  interAgentBoardLink,
  message,
  onActiveSpeechMessageChange,
  onCopyMessage,
  onOpenInterAgentGraph,
  onToggleExpanded,
  speakingMessageId,
  speechMaxTextChars,
  speechProviderAppId,
  speechProviderAvailable,
  speechProviderQualityProfile,
  visibleContent,
}: {
  expanded: boolean;
  interAgentBoardLink?: InterAgentBoardLink;
  message: ChatMessage;
  onActiveSpeechMessageChange: Dispatch<SetStateAction<string | null>>;
  onCopyMessage: CopyMessageHandler;
  onOpenInterAgentGraph?: (runId: string) => void;
  onToggleExpanded: (messageId: string) => void;
  speakingMessageId: string | null;
  speechMaxTextChars: number;
  speechProviderAppId: string;
  speechProviderAvailable: boolean;
  speechProviderQualityProfile: string;
  visibleContent: string;
}) {
  return (
    <div className="chatapp-agent-trace">
      <section className="chatapp-agent-block chatapp-agent-block--action">
        <div className="chatapp-message-copy-row chatapp-message-copy-row--agent">
          <div className="chatapp-agent-block__body">
            <MarkdownMessage content={visibleContent || "_No text output._"} />
          </div>
          {message.content ? <CopyMessageButton content={message.content} onCopyMessage={onCopyMessage} /> : null}
        </div>
        {interAgentBoardLink ? (
          <div className="chatapp-agent-block__actions">
            <InterAgentBoardButton
              className="chatapp-agent-message-board"
              onOpen={onOpenInterAgentGraph}
              runId={interAgentBoardLink.runId}
              state={interAgentBoardLink.state}
            />
          </div>
        ) : null}
        {message.content.length > 3200 ? (
          <button className="chatapp-message-action" onClick={() => onToggleExpanded(message.id)} type="button">
            {expanded ? "Collapse output" : "Expand full output"}
          </button>
        ) : null}
        <MessageFooter
          content={message.content}
          createdAt={message.createdAt}
          onCopy={onCopyMessage}
          speechControl={
            <MessageSpeechButton
              activeMessageId={speakingMessageId}
              content={visibleContent}
              maxTextChars={speechMaxTextChars}
              messageId={message.id}
              onActiveMessageChange={onActiveSpeechMessageChange}
              providerAvailable={speechProviderAvailable}
              providerAppId={speechProviderAppId}
              providerQualityProfile={speechProviderQualityProfile}
            />
          }
        />
      </section>
    </div>
  );
}

function MessageMeta({ message, onCopyMessage }: { message: ChatMessage; onCopyMessage: CopyMessageHandler }) {
  return (
    <div className="chatapp-bubble__meta">
      {message.content && (message.role === "human" || message.role === "agent") ? (
        <CopyMessageButton content={message.content} meta onCopyMessage={onCopyMessage} />
      ) : null}
      <time className="chatapp-bubble__time" dateTime={message.createdAt}>
        {formatMessageTime(message.createdAt)}
      </time>
    </div>
  );
}

function bubbleClass(message: ChatMessage) {
  if (message.role === "human") {
    return "is-human";
  }
  if (message.role === "agent" || message.role === "structured") {
    return "is-agent";
  }
  if (message.role === "tool" || message.role === "step") {
    return "is-tool-inline";
  }
  return "is-system";
}
