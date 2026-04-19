import type { ChatMessage } from "../api/client";

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
  messages,
}: {
  error: string | null;
  isLoading: boolean;
  messages: ChatMessage[];
}) {
  if (!messages.length && !isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll">
        <div className="chatapp-chat-scroll__inner">
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
      <div className="chatapp-chat-scroll__inner">
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
              </div>
            ) : (
              <div className="chatapp-agent-block">
                <div className="chatapp-agent-block__body">
                  <pre>{message.content}</pre>
                </div>
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
              <span className="chatapp-pending-turn__label">Codex sta lavorando</span>
            </div>
          </article>
        ) : null}
        {error ? <div className="chatapp-error">{error}</div> : null}
      </div>
    </section>
  );
}
