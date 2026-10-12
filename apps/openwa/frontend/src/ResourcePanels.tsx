import type { Session, Chat, Row, Connection } from "./api";
import { Icon } from "./Icons";

export function SessionSidebar({
  sessions,
  selected,
  connection,
  onCreate,
  onSelect,
}: {
  sessions: Session[];
  selected: string;
  connection: Connection;
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
          disabled={connection.role === "viewer" || connection.scoped}
          aria-label="New session"
        >
          <Icon name="plus" />
        </button>
      </div>
      {sessions.map((s) => (
        <button
          key={s.id}
          className={"session-row " + (selected === s.id ? "selected" : "")}
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
          Create a session to link your WhatsApp account.
        </p>
      )}
      <div className="sidebar-footer">
        <Icon name="link" size={16} />
        <span>OpenWA 0.24 · Self hosted</span>
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
  page,
  more,
  onPage,
  onManage,
  onTab,
  onSearch,
  onChat,
}: {
  session?: Session;
  tab: string;
  chats: Chat[];
  chat?: Chat;
  records: Row[];
  search: string;
  loading: boolean;
  page: number;
  more: boolean;
  onPage: (page: number) => void;
  onManage: () => void;
  onTab: (tab: string) => void;
  onSearch: (search: string) => void;
  onChat: (chat: Chat) => void;
}) {
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
            onClick={() => onTab(t)}
          >
            {t === "chats" ? "Chats" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      <label className="search">
        <Icon name="search" size={17} />
        <input
          aria-label="Search conversations"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search…"
        />
      </label>
      <div className="chat-rows">
        {tab === "chats"
          ? chats
              .filter((c) =>
                (c.name || c.id).toLowerCase().includes(search.toLowerCase()),
              )
              .map((c) => (
                <button
                  key={c.id}
                  className={
                    "chat-row " + (chat?.id === c.id ? "selected" : "")
                  }
                  onClick={() => onChat(c)}
                >
                  <span className="avatar">
                    {(c.name || c.id)[0].toUpperCase()}
                  </span>
                  <span className="chat-description">
                    <strong>{c.name || c.id.split("@")[0]}</strong>
                    <small>{c.lastMessage?.body || c.id}</small>
                  </span>
                  {!!c.unreadCount && (
                    <span className="unread">{c.unreadCount}</span>
                  )}
                </button>
              ))
          : records
              .filter((r) =>
                JSON.stringify(r).toLowerCase().includes(search.toLowerCase()),
              )
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
        {!loading && ((tab === "chats" && !chats.length) ||
          (tab !== "chats" && !records.length)) && (
          <p className="empty-hint">
            {session?.status === "ready"
              ? "No " + tab + " to show yet."
              : "Link a session to see its " + tab + "."}
          </p>
        )}
      </div>
      {(page > 0 || more) && <div className="pagination">
        <button disabled={loading || page === 0} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="small muted">Page {page + 1}</span>
        <button disabled={loading || !more} onClick={() => onPage(page + 1)}>Next</button>
      </div>}
    </section>
  );
}
