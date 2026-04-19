import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../api/client";
import { formatFileSize } from "../lib/attachments";
import { MarkdownMessage } from "./MarkdownMessage";

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
  messages,
}: {
  error: string | null;
  isLoading: boolean;
  loadingLabel: string;
  messages: ChatMessage[];
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [showScrollJump, setShowScrollJump] = useState(false);

  function scrollToBottom() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    setShowScrollJump(false);
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

  if (!messages.length && !isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll">
        <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
          <div className="chatapp-empty-panel chatapp-chat-empty__panel">
            <p className="chatapp-chat-list__subtitle">Nessun messaggio ancora.</p>
            <h2 className="chatapp-chat-panel__title">Fai una domanda</h2>
            <p className="chatapp-composer__hint">
              La sessione runtime appartiene al core. Il transcript e la UI sono proprietà dell'app Chat.
            </p>
          </div>
        </div>
      </section>
    );
  }
  return (
    <section className="chatapp-chat-scroll" aria-live="polite">
      <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
        {messages.map((message) => (
          <article
            className={`chatapp-bubble ${
              message.role === "human" ? "is-human" : message.role === "agent" ? "is-agent" : "is-system"
            } ${message.status === "failed" ? "is-error" : ""}`}
            key={message.id}
          >
            {message.role === "human" ? (
              <div className="chatapp-human-message">
                <div className="chatapp-human-message__text">{message.content}</div>
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
              <div className="chatapp-system-update">
                <span className="chatapp-system-update__icon" aria-hidden="true">
                  <span className="material-symbols-rounded">info</span>
                </span>
                <span>{message.content}</span>
              </div>
            ) : (
              <div className="chatapp-agent-trace">
                <section className="chatapp-agent-block chatapp-agent-block--action">
                  <div className="chatapp-agent-block__body">
                    <MarkdownMessage content={message.content || "_Nessun output testuale._"} />
                  </div>
                </section>
              </div>
            )}
            <div className="chatapp-bubble__meta">
              <time className="chatapp-bubble__time" dateTime={message.createdAt}>
                {formatTime(message.createdAt)}
              </time>
            </div>
          </article>
        ))}
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
        {error ? <div className="chatapp-error">{error}</div> : null}
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
