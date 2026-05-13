import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { AppReference, ChatMessage } from "../api/client";
import { formatFileSize } from "../lib/attachments";
import { findMentionTokens, referenceKey } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import { openAppRouteInShell } from "../lib/shellNavigation";
import { MarkdownMessage } from "./MarkdownMessage";
import { RuntimeStepMessage } from "./RuntimeStepMessage";
import { StructuredContentMessage } from "./StructuredContentMessage";
import { ToolCallInlineMessage } from "./ToolCallInlineMessage";
import { MorphingSpinner } from "./ui/morphing-spinner";

function formatTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

export function ChatTranscript({
  error,
  isLoading,
  loadingLabel,
  mentionItems,
  messages,
}: {
  error: string | null;
  isLoading: boolean;
  loadingLabel: string;
  mentionItems: MentionItem[];
  messages: ChatMessage[];
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [showScrollJump, setShowScrollJump] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());

  function scrollToBottom() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    setShowScrollJump(false);
  }

  function toggleExpanded(messageId: string) {
    setExpandedMessages((current) => {
      const next = new Set(current);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }

  async function copyMessage(content: string) {
    if (!content || !navigator.clipboard) {
      return;
    }
    await navigator.clipboard.writeText(content);
  }

  function updateScrollState() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    const nextIsNearBottom = distanceFromBottom < 96;
    setIsNearBottom(nextIsNearBottom);
    if (nextIsNearBottom) {
      setShowScrollJump(false);
    }
  }

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    if (isNearBottom) {
      viewport.scrollTop = viewport.scrollHeight;
      setShowScrollJump(false);
    } else {
      setShowScrollJump(true);
    }
  }, [messages.length, isLoading, error]);

  const latestToolMessageId =
    [...messages]
      .reverse()
      .find((message) => message.role === "tool" && (message.toolCalls?.length || message.toolCall))?.id || null;

  if (!messages.length && isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll" aria-busy="true" aria-live="polite">
        <div className="chatapp-chat-scroll__inner chatapp-chat-scroll__inner--skeleton" onScroll={updateScrollState} ref={viewportRef}>
          <ChatTranscriptSkeleton label={loadingLabel || "Loading history"} />
        </div>
      </section>
    );
  }

  if (!messages.length && !isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll">
        <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef} />
      </section>
    );
  }
  return (
    <section className="chatapp-chat-scroll" aria-live="polite">
      <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
        {messages.map((message) => {
          const shouldCollapse = message.role === "agent" && message.content.length > 3200 && !expandedMessages.has(message.id);
          const visibleContent = shouldCollapse ? `${message.content.slice(0, 3200)}\n\n...` : message.content;
          const hasMobileFooter = message.role === "human" || message.role === "agent";
          const toolCalls = message.role === "tool" ? (message.toolCalls?.length ? message.toolCalls : message.toolCall ? [message.toolCall] : []) : [];
          const isToolMessage = toolCalls.length > 0;
          return (
            <article
              className={`chatapp-bubble ${bubbleClass(message)} ${message.status === "failed" ? "is-error" : ""} ${
                hasMobileFooter ? "has-mobile-message-footer" : ""
              }`}
              key={message.id}
            >
              {message.role === "human" ? (
                <div className="chatapp-human-message">
                  <div className="chatapp-message-copy-row chatapp-message-copy-row--human">
                    <div className="chatapp-human-message__text">
                      {renderHumanMessageContent(message.content, message.appReferences || [], mentionItems)}
                    </div>
                    {message.content ? (
                      <button
                        aria-label="Copia messaggio"
                        className="chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy"
                        onClick={() => void copyMessage(message.content)}
                        title="Copia"
                        type="button"
                      >
                        <span aria-hidden="true" className="material-symbols-rounded">
                          content_copy
                        </span>
                      </button>
                    ) : null}
                  </div>
                  {message.attachments?.length ? (
                    <div className="chatapp-human-message__attachments">
                      {message.attachments.map((attachment) => (
                        <div
                          className={`chatapp-attachment-card is-readonly ${attachment.isImage ? "is-image" : ""} ${
                            attachment.warning ? "is-invalid" : ""
                          }`}
                          key={attachment.id}
                        >
                          {attachment.objectUrl && message.status === "pending" ? (
                            <img alt="" className="chatapp-attachment-card__preview" src={attachment.objectUrl} />
                          ) : (
                            <span className="chatapp-attachment-card__icon" aria-hidden="true">
                              <span className="material-symbols-rounded">description</span>
                            </span>
                          )}
                          <span className="chatapp-attachment-card__meta">
                            <span className="chatapp-attachment-card__name">{attachment.name}</span>
                            <span className="chatapp-attachment-card__detail">{formatFileSize(attachment.size)}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <MessageFooter content={message.content} createdAt={message.createdAt} onCopy={copyMessage} />
                </div>
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
                <div className="chatapp-agent-trace">
                  <section className="chatapp-agent-block chatapp-agent-block--action">
                    <div className="chatapp-message-copy-row chatapp-message-copy-row--agent">
                      <div className="chatapp-agent-block__body">
                        <MarkdownMessage content={visibleContent || "_Nessun output testuale._"} />
                      </div>
                      {message.content ? (
                        <button
                          aria-label="Copia messaggio"
                          className="chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy"
                          onClick={() => void copyMessage(message.content)}
                          title="Copia"
                          type="button"
                        >
                          <span aria-hidden="true" className="material-symbols-rounded">
                            content_copy
                          </span>
                        </button>
                      ) : null}
                    </div>
                    {message.content.length > 3200 ? (
                      <button className="chatapp-message-action" onClick={() => toggleExpanded(message.id)} type="button">
                        {expandedMessages.has(message.id) ? "Comprimi output" : "Espandi output completo"}
                      </button>
                    ) : null}
                    <MessageFooter content={message.content} createdAt={message.createdAt} onCopy={copyMessage} />
                  </section>
                </div>
              )}
              {isToolMessage ? null : (
                <div className="chatapp-bubble__meta">
                  {message.content && (message.role === "human" || message.role === "agent") ? (
                    <button
                      aria-label="Copia messaggio"
                      className="chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy chatapp-message-action--copy-meta"
                      onClick={() => void copyMessage(message.content)}
                      title="Copia"
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">
                        content_copy
                      </span>
                    </button>
                  ) : null}
                  <time className="chatapp-bubble__time" dateTime={message.createdAt}>
                    {formatTime(message.createdAt)}
                  </time>
                </div>
              )}
            </article>
          );
        })}
        {isLoading ? (
          <article className="chatapp-bubble is-agent">
            <div className="chatapp-pending-turn" aria-live="polite">
              <MorphingSpinner size="sm" className="chatapp-pending-turn__icon" />
              <span className="chatapp-pending-turn__label">{loadingLabel}</span>
            </div>
          </article>
        ) : null}
        {error ? (
          <div className="chatapp-error" role="alert">
            <span className="chatapp-error__icon material-symbols-rounded" aria-hidden="true">
              error
            </span>
            <span className="chatapp-error__label">{error}</span>
          </div>
        ) : null}
      </div>
      {showScrollJump ? (
        <button className="chatapp-chat-scroll-jump" onClick={scrollToBottom} type="button" aria-label="Vai all'ultimo messaggio">
          <span aria-hidden="true" className="material-symbols-rounded">
            arrow_downward
          </span>
        </button>
      ) : null}
    </section>
  );
}

function MessageFooter({
  content,
  createdAt,
  onCopy,
}: {
  content: string;
  createdAt: string;
  onCopy: (content: string) => Promise<void>;
}) {
  return (
    <div className="chatapp-message-mobile-footer">
      {content ? (
        <button
          aria-label="Copia messaggio"
          className="chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy"
          onClick={() => void onCopy(content)}
          title="Copia"
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            content_copy
          </span>
        </button>
      ) : null}
      <time className="chatapp-bubble__time" dateTime={createdAt}>
        {formatTime(createdAt)}
      </time>
    </div>
  );
}

function ChatTranscriptSkeleton({ label }: { label: string }) {
  return (
    <div className="chatapp-transcript-skeleton" role="status" aria-label={label}>
      <SkeletonBubble variant="human" lines={["wide", "medium"]} />
      <SkeletonBubble variant="agent" lines={["wide", "wide", "medium", "tiny"]} />
      <SkeletonBubble variant="agent" lines={["medium", "wide", "wide", "short"]} />
      <SkeletonBubble variant="agent" lines={["wide", "medium", "medium"]} />
      <SkeletonBubble variant="agent" lines={["medium", "wide", "short"]} />
      <SkeletonBubble variant="agent" lines={["wide", "short"]} />
    </div>
  );
}

function SkeletonBubble({ lines, variant }: { lines: Array<"wide" | "medium" | "short" | "tiny">; variant: "agent" | "human" }) {
  if (variant === "human") {
    return (
      <article className="chatapp-bubble is-human chatapp-transcript-skeleton__bubble chatapp-transcript-skeleton__bubble--human" aria-hidden="true">
        <div className="chatapp-human-message">
          {lines.map((line, index) => (
            <span className={`chatapp-transcript-skeleton__line chatapp-transcript-skeleton__line--${line}`} key={`${line}-${index}`} />
          ))}
        </div>
      </article>
    );
  }

  return (
    <article className="chatapp-bubble is-agent chatapp-transcript-skeleton__bubble chatapp-transcript-skeleton__bubble--agent" aria-hidden="true">
      <div className="chatapp-agent-trace">
        <section className="chatapp-agent-block chatapp-agent-block--action">
          <div className="chatapp-agent-block__body">
            {lines.map((line, index) => (
              <span className={`chatapp-transcript-skeleton__line chatapp-transcript-skeleton__line--${line}`} key={`${line}-${index}`} />
            ))}
          </div>
        </section>
      </div>
    </article>
  );
}

function renderHumanMessageContent(content: string, appReferences: AppReference[], mentionItems: MentionItem[]) {
  const tokenMatches = findMentionTokens(content, mentionItems).map((token) => ({
    kind: token.item.kind,
    id: token.item.id,
    label: token.item.label,
    appId: token.item.reference?.type === "entity" ? token.item.reference.app_id : undefined,
    deepLink: token.item.reference?.type === "entity" ? token.item.reference.deep_link : undefined,
    exists: token.item.reference?.type === "entity" ? token.item.reference.exists : undefined,
    start: token.start,
    end: token.end,
  }));
  const fallbackAppMatches = appReferences
    .flatMap((reference) => fallbackMatchesForAppReference(content, reference))
    .filter((match) => !tokenMatches.some((token) => rangesOverlap(token, match)));
  const matches = [...tokenMatches, ...fallbackAppMatches]
    .sort((left, right) => left.start - right.start)
    .filter((match, index, sorted) => index === 0 || match.start >= sorted[index - 1].end);
  if (!matches.length) {
    return content;
  }
  const segments: ReactNode[] = [];
  let cursor = 0;
  matches.forEach((match) => {
    if (match.start > cursor) {
      segments.push(content.slice(cursor, match.start));
    }
    segments.push(<MentionReferenceChip key={`${match.kind}:${match.id}:${match.start}`} match={match} />);
    cursor = match.end;
  });
  if (cursor < content.length) {
    segments.push(content.slice(cursor));
  }
  return segments;
}

export type MessageMentionMatch = {
  kind: MentionItem["kind"];
  id: string;
  label: string;
  start: number;
  end: number;
  appId?: string;
  deepLink?: string;
  exists?: boolean;
};

export function fallbackMatchesForAppReference(content: string, reference: AppReference): MessageMentionMatch[] {
  if (reference.type === "entity") {
    const label = reference.label?.trim() || reference.entity_id;
    const marker = `[ref:${reference.app_id}/${reference.entity_type}/${reference.entity_id}]`;
    const markerMatches = fallbackEntityReferenceCandidates(content, marker);
    const labelMatches = markerMatches.length ? [] : fallbackReferenceCandidates(content, [`@${label}`]);
    return [...markerMatches, ...labelMatches].map((match) => ({
      ...match,
      kind: "entity" as const,
      id: referenceKey(reference),
      appId: reference.app_id,
      label,
      deepLink: reference.deep_link,
      exists: reference.exists,
    }));
  }
  const label = reference.label?.trim();
  const candidates = [`@${reference.app_id}`, label ? `@${label}` : ""].filter(Boolean);
  return fallbackReferenceCandidates(content, candidates).map((match) => ({
    ...match,
    kind: "app" as const,
    id: reference.app_id,
    label: reference.label || reference.app_id,
  }));
}

function fallbackEntityReferenceCandidates(content: string, marker: string): Pick<MessageMentionMatch, "start" | "end">[] {
  const matches: Pick<MessageMentionMatch, "start" | "end">[] = [];
  let searchFrom = 0;
  while (searchFrom < content.length) {
    const markerStart = content.indexOf(marker, searchFrom);
    if (markerStart < 0) {
      break;
    }
    const mentionStart = entityReferenceMentionStart(content, markerStart);
    matches.push({
      start: mentionStart ?? markerStart,
      end: markerStart + marker.length,
    });
    searchFrom = markerStart + marker.length;
  }
  return matches;
}

function entityReferenceMentionStart(content: string, markerStart: number): number | null {
  if (markerStart <= 0 || !/[ \t]/.test(content[markerStart - 1])) {
    return null;
  }
  let labelEnd = markerStart;
  while (labelEnd > 0 && /[ \t]/.test(content[labelEnd - 1])) {
    labelEnd -= 1;
  }
  const separator = content.slice(labelEnd, markerStart);
  if (!separator || !/^[ \t]+$/.test(separator)) {
    return null;
  }
  const atIndex = content.lastIndexOf("@", labelEnd - 1);
  if (atIndex < 0) {
    return null;
  }
  if (atIndex > 0 && !/\s/.test(content[atIndex - 1])) {
    return null;
  }
  const label = content.slice(atIndex + 1, labelEnd).trim();
  if (!label || /[\r\n\[\]]/.test(label)) {
    return null;
  }
  return atIndex;
}

function fallbackReferenceCandidates(content: string, candidates: string[]): Pick<MessageMentionMatch, "start" | "end">[] {
  return candidates
    .filter(Boolean)
    .map((candidate) => {
      const start = content.indexOf(candidate);
      return start >= 0 ? { start, end: start + candidate.length } : null;
    })
    .filter((match): match is Pick<MessageMentionMatch, "start" | "end"> => Boolean(match));
}

function rangesOverlap(left: Pick<MessageMentionMatch, "start" | "end">, right: Pick<MessageMentionMatch, "start" | "end">): boolean {
  return left.start < right.end && right.start < left.end;
}

function MentionReferenceChip({ match }: { match: MessageMentionMatch }) {
  const className = `chatapp-message-reference-chip is-${match.kind} ${match.exists === false ? "is-missing" : ""}`;
  const title = match.kind === "entity" ? `reference: ${match.id}` : `${match.kind === "app" ? "app_id" : "skill_id"}: ${match.id}`;
  const content = (
    <>
      <span className="chatapp-message-reference-chip__kind">{match.kind === "entity" ? "Record" : match.kind === "app" ? "App" : "Skill"}</span>
      <span className="chatapp-message-reference-chip__label">{match.exists === false ? `${match.label} (missing)` : match.label}</span>
    </>
  );
  if (match.kind === "entity" && match.appId && match.deepLink) {
    return (
      <button
        className={className}
        data-reference-id={match.id}
        onClick={() => openEntityReference(match.appId || "", match.deepLink || "")}
        title={title}
        type="button"
      >
        {content}
      </button>
    );
  }
  return (
    <span className={className} data-reference-id={match.id} title={title}>
      {content}
    </span>
  );
}

function openEntityReference(appId: string, deepLink: string): void {
  const prefix = `/app/${appId}/`;
  const appPage = deepLink.startsWith(prefix) ? deepLink.slice(prefix.length) : "";
  if (appPage) {
    openAppRouteInShell(appId, appPage);
  }
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
