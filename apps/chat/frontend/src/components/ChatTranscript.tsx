import { useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatThread } from "../api/client";
import { formatFileSize } from "../lib/attachments";
import { MarkdownMessage } from "./MarkdownMessage";
import { RuntimeStepMessage } from "./RuntimeStepMessage";
import { StructuredContentMessage } from "./StructuredContentMessage";
import { ToolCallInlineMessage } from "./ToolCallInlineMessage";

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
  activeThread,
  error,
  isLoading,
  loadingLabel,
  messages,
}: {
  activeThread: ChatThread | null;
  error: string | null;
  isLoading: boolean;
  loadingLabel: string;
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

  if (!messages.length && isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll" aria-busy="true" aria-live="polite">
        <div className="chatapp-chat-scroll__inner chatapp-chat-scroll__inner--centered" onScroll={updateScrollState} ref={viewportRef}>
          <div className="chatapp-loading-panel">
            <div className="chatapp-pending-turn" aria-live="polite">
              <span className="chatapp-pending-turn__icon" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <span className="chatapp-pending-turn__label">{loadingLabel || "Loading history"}</span>
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (!messages.length && !isLoading && !error) {
    const agentLabel = activeThread?.agent_label || activeThread?.title || "";
    return (
      <section className="chatapp-chat-scroll">
        <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
          <div className="chatapp-empty-panel chatapp-chat-empty__panel">
            <p className="chatapp-chat-list__subtitle">{agentLabel ? "Agent ready" : "Nessun messaggio ancora."}</p>
            <h2 className="chatapp-chat-panel__title">{agentLabel ? agentLabel : "Fai una domanda"}</h2>
            <p className="chatapp-composer__hint">{agentLabel ? `Fai una domanda a ${agentLabel}.` : "Scegli una chat o avvia una nuova sessione."}</p>
          </div>
        </div>
      </section>
    );
  }
  return (
    <section className="chatapp-chat-scroll" aria-live="polite">
      <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
        {messages.map((message) => {
          const shouldCollapse = message.role === "agent" && message.content.length > 3200 && !expandedMessages.has(message.id);
          const visibleContent = shouldCollapse ? `${message.content.slice(0, 3200)}\n\n...` : message.content;
          return (
            <article className={`chatapp-bubble ${bubbleClass(message)} ${message.status === "failed" ? "is-error" : ""}`} key={message.id}>
              {message.role === "human" ? (
                <div className="chatapp-human-message">
                  <div className="chatapp-human-message__text">{message.content}</div>
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
                  {message.attachments?.length ? (
                    <div className="chatapp-human-message__attachments">
                      {message.attachments.map((attachment) => (
                        <div
                          className={`chatapp-attachment-card is-readonly ${attachment.isImage ? "is-image" : ""} ${
                            attachment.warning ? "is-invalid" : ""
                          }`}
                          key={attachment.id}
                        >
                          {attachment.objectUrl ? (
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
                </div>
              ) : message.role === "system" ? (
                <div className={`chatapp-system-update ${message.status === "failed" ? "chatapp-system-update--error" : ""}`}>
                  <span className="chatapp-system-update__icon" aria-hidden="true">
                    <span className="material-symbols-rounded">{message.status === "failed" ? "error" : "info"}</span>
                  </span>
                  <span className="chatapp-system-update__label">{message.content}</span>
                </div>
              ) : message.role === "tool" && (message.toolCalls?.length || message.toolCall) ? (
                <ToolCallInlineMessage toolCalls={message.toolCalls?.length ? message.toolCalls : [message.toolCall!]} />
              ) : message.role === "step" && message.step ? (
                <RuntimeStepMessage step={message.step} />
              ) : message.role === "structured" && message.structuredContent ? (
                <StructuredContentMessage content={message.structuredContent} messageId={message.id} />
              ) : (
                <div className="chatapp-agent-trace">
                  <section className="chatapp-agent-block chatapp-agent-block--action">
                    <div className="chatapp-agent-block__body">
                      <MarkdownMessage content={visibleContent || "_Nessun output testuale._"} />
                    </div>
                    {message.content.length > 3200 ? (
                      <button className="chatapp-message-action" onClick={() => toggleExpanded(message.id)} type="button">
                        {expandedMessages.has(message.id) ? "Comprimi output" : "Espandi output completo"}
                      </button>
                    ) : null}
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
                  </section>
                </div>
              )}
              <div className="chatapp-bubble__meta">
                <time className="chatapp-bubble__time" dateTime={message.createdAt}>
                  {formatTime(message.createdAt)}
                </time>
              </div>
            </article>
          );
        })}
        {isLoading ? (
          <article className="chatapp-bubble is-agent">
            <div className="chatapp-pending-turn" aria-live="polite">
              <span className="chatapp-pending-turn__icon" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
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
