import type { Session, Chat, Row, Connection } from "./api";
import { Icon } from "./Icons";

export function SessionSidebar({
  sessions,
  selected,
  connection,
  online = true,
  onCreate,
  onSelect,
}: {
  sessions: Session[];
  selected: string;
  connection: Connection;
  online?: boolean;
  onCreate: () => void;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="session-sidebar">
      <div className="panel-heading">
        <p className="eyebrow">SESSIONS</p>
        <button
          className="icon-button"
          onClick={onCreate}
          disabled={!online || connection.role === "viewer" || connection.scoped}
          aria-label="New session"
        >
          <Icon name="plus" />
        </button>
      </div>
      <div className="session-rows">{sessions.map((s) => (
        <button
          key={s.id}
          className={"session-row " + (selected === s.id ? "selected" : "")}
          aria-pressed={selected === s.id}
          onClick={() => {
            onSelect(s.id);
          }}
        >
          <span className={"session-dot " + s.status} />
          <span>
            <strong>{s.name}</strong>
            <small>{s.phone || s.status.replaceAll("_", " ")}</small>
          </span>
        </button>
      ))}
      {sessions.length === 0 && (
        <p className="empty-hint">
          {!online ? "Waiting for the gateway connection…" : connection.role === "viewer" || connection.scoped ? "No sessions are available for this connection." : "Create a session to link your WhatsApp account."}
        </p>
      )}
      </div>
      <div className="sidebar-footer">
        <Icon name="link" size={16} />
        <span>WhatsApp linked devices</span>
      </div>
    </aside>
  );
}

export function ResourcePanel({
  session,
  tab,
  chats,
  chat,
  records,
  search,
  loading,
  error = "",
  online = true,
  page,
  more,
  onPage,
  onManage,
  onTab,
  onSearch,
  onChat,
  onRetry,
}: {
  session?: Session;
  tab: string;
  chats: Chat[];
  chat?: Chat;
  records: Row[];
  search: string;
  loading: boolean;
  error?: string;
  online?: boolean;
  page: number;
  more: boolean;
  onPage: (page: number) => void;
  onManage: () => void;
  onTab: (tab: string) => void;
  onSearch: (search: string) => void;
  onChat: (chat: Chat) => void;
  onRetry?: () => void;
}) {
  const query = search.trim().toLowerCase();
  const filteredChats = chats.filter((item) => (item.name || item.id).toLowerCase().includes(query));
  const filteredRecords = records.filter((item) => JSON.stringify(item).toLowerCase().includes(query));
  const count = tab === "chats" ? filteredChats.length : filteredRecords.length;
  const readable = !!session && (session.status === "ready" || ["webhooks", "templates"].includes(tab));
  return (
    <section className="chat-list">
      <div className="panel-heading">
        <div>
          <h2>{session?.name || "Your conversations"}</h2>
          {session && (
            <span className={"status-pill " + session.status}>
              {session.status.replaceAll("_", " ")}
            </span>
          )}
        </div>
        {session && (
          <button
            className="icon-button"
            onClick={onManage}
            aria-label="Manage session"
          >
            <Icon name="settings" />
          </button>
        )}
      </div>
      <nav className="tabs" aria-label="Session resources">
        {["chats", "contacts", "webhooks", "templates"].map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            aria-pressed={tab === t}
            disabled={!session}
            onClick={() => onTab(t)}
          >
            {t === "chats" ? "Chats" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      <label className="search">
        <Icon name="search" size={17} />
        <input
          aria-label={"Search " + (tab === "chats" ? "conversations" : tab)}
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={"Search " + tab + " on this page…"}
          disabled={!readable}
        />
      </label>
      <div className="chat-rows" aria-busy={loading}>
        {tab === "chats"
          ? filteredChats
              .map((c) => (
                <button
                  key={c.id}
                  className={
                    "chat-row " + (chat?.id === c.id ? "selected" : "")
                  }
                  onClick={() => onChat(c)}
                  aria-pressed={chat?.id === c.id}
                >
                  <span className="avatar">
                    {(c.name || c.id)[0].toUpperCase()}
                  </span>
                  <span className="chat-description">
                    <strong>{c.name || c.id.split("@")[0]}</strong>
                    <small>{c.lastMessage || c.id}</small>
                  </span>
                  {!!c.unreadCount && (
                    <span className="unread">{c.unreadCount}</span>
                  )}
                </button>
              ))
          : filteredRecords
              .map((r, i) => (
                <article className="record-row" key={String(r.id || i)}>
                  <strong>
                    {String(
                      r.name ||
                        r.displayName ||
                        r.pushName ||
                        r.url ||
                        r.id ||
                        "Item",
                    )}
                  </strong>
                  <p>
                    {String(
                      r.body || r.content || r.number || r.description || "",
                    )}
                  </p>
                </article>
              ))}
        {loading && <p className="empty-hint" role="status">Refreshing {tab}…</p>}
        {error && <div className="resource-error" role="alert"><p>{error}</p>
          <button onClick={onRetry} disabled={loading}>Retry {tab}</button>
        </div>}
        {!loading && !error && count === 0 && (
          <p className="empty-hint">
            {!online ? "Reconnect the gateway to refresh " + tab + "." : query && readable ? "No matches on this page. Try another search or page." : readable
              ? "No " + tab + " to show yet."
              : "Link a session to see its " + tab + "."}
          </p>
        )}
      </div>
      {(page > 0 || more) && <div className="pagination">
        <button disabled={page === 0} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="small muted">Page {page + 1}</span>
        <button disabled={!more} onClick={() => onPage(page + 1)}>Next</button>
      </div>}
    </section>
  );
}
