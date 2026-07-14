import { lazy, Suspense, type Dispatch, type SetStateAction } from "react";
import type { ChatMessage } from "../api/client";
import type { InterAgentBoardLink } from "../lib/interAgentTranscript";
import type { MentionItem } from "../lib/mentions";
import { HumanMessage } from "./HumanMessage";
import { InterAgentBoardButton } from "./InterAgentBoardButton";
import { CopyMessageButton, type CopyMessageHandler } from "./MessageCopyButton";
import { MessageFooter, formatMessageTime } from "./MessageFooter";
import { MessageSpeechButton } from "./MessageSpeechButton";
import { isExpandableRuntimeStep, RuntimeStepMessage } from "./RuntimeStepMessage";
import { StructuredContentMessage } from "./StructuredContentMessage";
import { ToolCallInlineMessage } from "./ToolCallInlineMessage";

const LazyMarkdownMessage = lazy(async () => {
  const module = await import("./MarkdownMessage");
  return { default: module.MarkdownMessage };
});

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
  const isExpandableStepMessage = message.role === "step" && message.step ? isExpandableRuntimeStep(message.step) : false;

  return (
    <article
      className={`chatapp-bubble ${bubbleClass(message)} ${message.status === "failed" ? "is-error" : ""} ${
        hasMobileFooter ? "has-mobile-message-footer" : ""
      }`}
    >
      {message.sourceLabel && message.role !== "human" ? <MessageSource label={message.sourceLabel} /> : null}
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
        <RuntimeStepMessage createdAt={message.createdAt} step={message.step} />
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
      {isToolMessage || isExpandableStepMessage ? null : <MessageMeta message={message} onCopyMessage={onCopyMessage} />}
    </article>
  );
}

function MessageSource({ label }: { label: string }) {
  return (
    <div className="chatapp-message-source" aria-label={`Agent source: ${label}`}>
      <span className="material-symbols-rounded" aria-hidden="true">
        smart_toy
      </span>
      <span>{label}</span>
    </div>
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
            <AgentMarkdownMessage content={visibleContent || "_No text output._"} />
          </div>
          {message.content ? <CopyMessageButton content={message.content} onCopyMessage={onCopyMessage} /> : null}
        </div>
        {message.content.length > 3200 ? (
          <button className="chatapp-message-action" onClick={() => onToggleExpanded(message.id)} type="button">
            {expanded ? "Collapse output" : "Expand full output"}
          </button>
        ) : null}
        <MessageFooter
          content={message.content}
          createdAt={message.createdAt}
          leadingControl={
            interAgentBoardLink ? (
              <InterAgentBoardButton
                className="chatapp-agent-message-board"
                onOpen={onOpenInterAgentGraph}
                runId={interAgentBoardLink.runId}
                state={interAgentBoardLink.state}
              />
            ) : null
          }
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

function AgentMarkdownMessage({ content }: { content: string }) {
  return (
    <Suspense fallback={<PlainTextMarkdownFallback content={content} />}>
      <LazyMarkdownMessage content={content} />
    </Suspense>
  );
}

function PlainTextMarkdownFallback({ content }: { content: string }) {
  return <p className="chatapp-markdown-fallback">{content}</p>;
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
