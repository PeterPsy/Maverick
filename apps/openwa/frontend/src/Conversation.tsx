import { useEffect, useState, useRef, type FormEvent } from "react";
import { operation, items, type Chat, type Session, type Message } from "./api";
import { Icon } from "./Icons";
import { maverickAppIsVisible, observeMaverickVisibility } from "@maverick/pwa-cache";

export function Conversation({
  session,
  chat,
  canSend,
  onBack,
}: {
  session: Session;
  chat: Chat;
  canSend: boolean;
  onBack: () => void;
}) {
  const [rows, setRows] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(false);
  const [quote, setQuote] = useState<Message>();
  const pending = useRef<{ text: string; quote?: string; key: string } | null>(null);
  useEffect(() => {
    setPage(0);
    setRows([]);
    setDraft("");
    setError("");
    setQuote(undefined);
    pending.current = null;
  }, [session.id, chat.id]);
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
          setError("");
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
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
    if (busy || !draft.trim() || !canSend || session.status !== "ready") return;
    setBusy(true);
    setError("");
    if (!pending.current || pending.current.text !== draft || pending.current.quote !== quote?.waMessageId)
      pending.current = { text: draft, quote: quote?.waMessageId, key: crypto.randomUUID() };
    try {
      await operation(quote ? "messages.reply" : "messages.send", {
        session_id: session.id,
        chat_id: chat.id,
        text: draft,
        ...(quote ? { message_id: quote.waMessageId } : {}),
        idempotency_key: pending.current.key,
      });
      setDraft("");
      setQuote(undefined);
      pending.current = null;
      setPage(0);
      const data = await operation("messages.list", {
        session_id: session.id,
        chat_id: chat.id,
      });
      setRows(items<Message>(data).reverse());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
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
                  type="button" className="reply-button" disabled={busy}
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
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {quote && <div className="reply-preview">
        <div><strong>Replying to</strong><p>{quote.body || `[${quote.type || "Message"}]`}</p></div>
        <button className="icon-button" onClick={() => setQuote(undefined)} aria-label="Cancel reply" disabled={busy}>
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
          rows={2}
        />
        <button
          className="primary send-button"
          disabled={busy || !canSend || !draft.trim() || session.status !== "ready"}
          aria-label="Send message"
        >
          <Icon name="send" />
          {busy ? "Sending…" : "Send"}
        </button>
      </form>
    </section>
  );
}
