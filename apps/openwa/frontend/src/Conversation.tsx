import { useEffect, useState, type FormEvent } from "react";
import { BackendError, operation, items, type Chat, type Session, type Message } from "./api";
import { Icon } from "./Icons";
import { Dialog } from "./Dialog";
import { retryBlocked, sendAttemptKey, useSendAttempt, type SendAttempt } from "./sendAttempts";
import { maverickAppIsVisible, observeMaverickVisibility } from "@maverick/pwa-cache";

export function Conversation({
  session,
  chat,
  canSend,
  sendScope,
  onBack,
}: {
  session: Session;
  chat: Chat;
  canSend: boolean;
  sendScope: string;
  onBack: () => void;
}) {
  const { attempt, storageError, save, mounted } = useSendAttempt(sendAttemptKey(sendScope, session.id, chat.id));
  const [rows, setRows] = useState<Message[]>([]);
  const [draft, setDraft] = useState(attempt?.text || "");
  const [readError, setReadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(false);
  const [quote, setQuote] = useState<Message | undefined>(attempt?.quote);
  const [confirmNew, setConfirmNew] = useState(false);
  const blocked = retryBlocked(attempt);
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await operation<unknown>("messages.list", {
          session_id: session.id,
          chat_id: chat.id,
          limit: 50,
          offset: page * 50,
        });
        if (alive) {
          const result = items<Message>(data);
          setRows(result.slice().reverse());
          setMore(result.length === 50);
          setReadError("");
        }
      } catch (e) {
        if (alive) setReadError((e as Error).message);
      } finally {
        if (alive) setLoading(false);
      }
    }
    setLoading(true);
    const stop = observeMaverickVisibility((visible) => { if (visible) load(); });
    const timer = setInterval(() => {
      if (maverickAppIsVisible()) load();
    }, 8000);
    return () => {
      alive = false;
      stop();
      clearInterval(timer);
    };
  }, [session.id, chat.id, page]);
  async function send(e: FormEvent) {
    e.preventDefault();
    if (busy || storageError || retryBlocked(attempt) || !draft.trim() || !canSend || session.status !== "ready") return;
    const current: SendAttempt = attempt || { text: draft, quote, key: crypto.randomUUID(),
      createdAt: Date.now(), state: "in_progress", error: "This send has no confirmed outcome. Check the conversation before retrying." };
    // Persist before handing anything to the provider, including the quoted message.
    if (!save({ ...current, state: "in_progress" })) return;
    setBusy(true);
    try {
      await operation(current.quote ? "messages.reply" : "messages.send", {
        session_id: session.id,
        chat_id: chat.id,
        text: current.text,
        ...(current.quote ? { message_id: current.quote.waMessageId } : {}),
        idempotency_key: current.key,
      });
    } catch (e) {
      const error = e as Error;
      const state = error instanceof BackendError && error.code === "IDEMPOTENCY_KEY_IN_PROGRESS" ? "in_progress"
        : error instanceof BackendError && error.status === 409 ? "unknown" : "retryable";
      save({ ...current, state, error: error.message });
      if (mounted.current) setBusy(false);
      return;
    }
    // A read failure after a confirmed send must never become a send failure.
    const cleared = save(null);
    if (!mounted.current) return;
    if (cleared) {
      setDraft("");
      setQuote(undefined);
    }
    setPage(0);
    try {
      const data = await operation("messages.list", {
        session_id: session.id,
        chat_id: chat.id,
      });
      if (mounted.current) {
        setRows(items<Message>(data).reverse());
        setReadError("");
      }
    } catch (e) {
      if (mounted.current) setReadError((e as Error).message);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function resolve(present: boolean) {
    if (!save(null)) return;
    if (present) { setDraft(""); setQuote(undefined); }
    setConfirmNew(false);
  }
  return (
    <section className="conversation">
      <header className="conversation-heading">
        <button
          className="icon-button mobile-only"
          onClick={onBack}
          aria-label="Back to conversations"
        >
          <Icon name="back" />
        </button>
        <span className="avatar">
          {(chat.name || chat.id).slice(0, 1).toUpperCase()}
        </span>
        <div>
          <h2>{chat.name || chat.id.split("@")[0]}</h2>
          <p className="small muted">
            {chat.isGroup ? "Group conversation" : chat.id}
          </p>
        </div>
        <span className="conversation-session">{session.name}</span>
      </header>
      <div className="messages" aria-live="polite">
        {(page > 0 || more) && (
          <div className="pagination">
            <button disabled={!more} onClick={() => setPage((p) => p + 1)}>
              Older messages
            </button>
            <button disabled={!page} onClick={() => setPage((p) => p - 1)}>
              Newer messages
            </button>
          </div>
        )}
        {loading && rows.length === 0 ? (
          <p className="empty-inline">Loading messages…</p>
        ) : rows.length === 0 ? (
          <div className="empty-inline">
            <Icon name="chat" size={36} />
            <h3>A fresh conversation</h3>
            <p>Messages will appear here when this session receives them.</p>
          </div>
        ) : (
          rows.map((message) => (
            <article
              key={message.id}
              className={
                "message " +
                (message.direction === "outgoing" ? "outgoing" : "incoming")
              }
            >
              <p>{message.body || `[${message.type || "Message"}]`}</p>
              <footer>
                {message.waMessageId && canSend && <button
                  type="button" className="reply-button" disabled={busy || !!attempt || !!storageError}
                  onClick={() => setQuote(message)} aria-label="Reply to this message"
                >Reply</button>}
                {message.timestamp
                  ? new Date(message.timestamp * 1000).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : ""}
                {message.direction === "outgoing" && (
                  <span>{message.status}</span>
                )}
              </footer>
            </article>
          ))
        )}
      </div>
      {readError && <div className="error-banner" role="alert">{readError}</div>}
      {(storageError || attempt) && (
        <div className="error-banner" role="alert">
          <p>{storageError || (blocked
            ? "The send outcome is uncertain. Check the conversation before preparing another send."
            : attempt?.error)}</p>
          {attempt && !busy && (blocked || attempt.state !== "in_progress") && !storageError && <div className="send-recovery-actions">
            <button type="button" onClick={() => resolve(true)}>I found the message</button>
            <button type="button" onClick={() => setConfirmNew(true)}>Prepare a new send</button>
          </div>}
        </div>
      )}
      {quote && <div className="reply-preview">
        <div><strong>Replying to</strong><p>{quote.body || `[${quote.type || "Message"}]`}</p></div>
        <button className="icon-button" onClick={() => setQuote(undefined)} aria-label="Cancel reply" disabled={busy || !!attempt || !!storageError}>
          <Icon name="close" size={16} />
        </button>
      </div>}
      <form className="composer" onSubmit={send}>
        <textarea
          aria-label="Message"
          placeholder={canSend ? "Write a message…" : "Sending is unavailable for this connection"}
          maxLength={4096}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={busy || !canSend || session.status !== "ready"}
          readOnly={!!attempt || !!storageError}
          rows={2}
        />
        <button
          className="primary send-button"
          disabled={busy || blocked || !!storageError || !canSend || !draft.trim() || session.status !== "ready"}
          aria-label="Send message"
        >
          <Icon name="send" />
          {busy ? "Sending…" : attempt ? "Retry same send" : "Send"}
        </button>
      </form>
      {confirmNew && <Dialog label="Prepare a new send" onClose={() => setConfirmNew(false)}>
        <div className="modal">
          <h2>Check the conversation first</h2>
          <p>The earlier message may have arrived. A new send can deliver it again. Continue only after checking that it is missing.</p>
          <div className="send-recovery-actions">
            <button type="button" onClick={() => setConfirmNew(false)}>Keep previous attempt</button>
            <button type="button" className="primary" onClick={() => resolve(false)}>I checked: prepare a new send</button>
          </div>
        </div>
      </Dialog>}
    </section>
  );
}
