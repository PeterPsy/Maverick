import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  callBackend,
  operation,
  items,
  type Status,
  type Session,
  type Chat,
  type Row,
} from "./api";
import { Icon } from "./Icons";
import { ConnectionSettings } from "./ConnectionSettings";
import { SessionPanel } from "./SessionPanel";
import { Conversation } from "./Conversation";
import { SessionSidebar, ResourcePanel } from "./ResourcePanels";
import { useMaverickHost } from "./host";
import { Dialog } from "./Dialog";
import { maverickAppIsVisible, observeMaverickVisibility } from "@maverick/pwa-cache";

export function App() {
  const [status, setStatus] = useState<Status>();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [chat, setChat] = useState<Chat>();
  const [error, setError] = useState("");
  const [settings, setSettings] = useState(false);
  const [manage, setManage] = useState(false);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("chats");
  const [records, setRecords] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(false);
  const [revision, setRevision] = useState(0);
  const [online, setOnline] = useState<boolean>();
  const session = sessions.find((s) => s.id === selected);
  const refresh = useCallback(async () => {
    try {
      const s = await callBackend<Status>({ action: "status" });
      setStatus(s);
      if (s.connection.configured && s.connection.credential_available) {
        const rows = items<Session>(await operation("sessions.list"));
        setOnline(true);
        setSessions(rows);
        setSelected((previous) =>
          rows.some((r) => r.id === previous) ? previous : rows[0]?.id || "",
        );
      }
      setError("");
      setRevision((value) => value + 1);
    } catch (e) {
      setOnline(false);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const stop = observeMaverickVisibility((visible) => { if (visible) refresh(); });
    const timer = setInterval(() => {
      if (maverickAppIsVisible()) refresh();
    }, 10000);
    return () => { stop(); clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    let live = true;
    if (selected && (session?.status === "ready" || ["webhooks", "templates"].includes(tab))) {
      setResourceLoading(true);
      operation(tab + ".list", { session_id: selected, limit: 50, offset: page * 50 })
        .then((data) => {
          if (live) {
            const rows = items<Chat & Row>(data);
            if (tab === "chats") setChats(rows);
            else setRecords(rows);
            setMore(rows.length === 50);
          }
        })
        .catch((e) => {
          if (live) setError((e as Error).message);
        })
        .finally(() => { if (live) setResourceLoading(false); });
    } else {
      setResourceLoading(false);
      setChats([]);
      setRecords([]);
      setMore(false);
    }
    return () => {
      live = false;
    };
  }, [selected, tab, session?.status, page, revision]);
  useEffect(() => {
    setChat(undefined);
    setChats([]);
    setRecords([]);
    setSearch("");
    setPage(0);
    setMore(false);
  }, [selected, tab]);
  useMaverickHost(refresh, setSelected);
  async function newSession(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await operation<Session>("session.create", { name });
      setCreate(false);
      setName("");
      await refresh();
      setSelected(created.id);
      setManage(true);
      await operation("session.start", { session_id: created.id });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!status)
    return (
      <main className="setup-page">
        <div className="loading-card">
          {loading ? "Opening OpenWA…" : error}
          <button onClick={refresh}>Retry</button>
        </div>
      </main>
    );
  if (!status.connection.configured || !status.connection.credential_available)
    return (
      <main className="setup-page">
        <ConnectionSettings status={status} onSaved={refresh} />
        {error && <p className="error-banner">{error}</p>}
      </main>
    );
  return (
    <main className={"app-shell " + (chat ? "chat-open" : "")}>
      <header className="app-heading">
        <div className="app-identity">
          <span className="brand-icon">
            <Icon name="chat" size={24} />
          </span>
          <div>
            <h1>OpenWA</h1>
            <p>WhatsApp, in your workspace</p>
          </div>
        </div>
        <div className="heading-actions">
          <span className="gateway-label">
            <span className={"dot " + (online === false ? "offline" : "")} />
            {online === undefined ? "Checking gateway…" : online ? "Gateway connected" : "Gateway unavailable"}
          </span>
          <button
            className="icon-button"
            onClick={refresh}
            aria-label="Refresh"
          >
            <Icon name="refresh" />
          </button>
          {status.can_configure && (
            <button
              className="icon-button"
              onClick={() => setSettings(true)}
              aria-label="Gateway settings"
            >
              <Icon name="settings" />
            </button>
          )}
        </div>
      </header>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button
            className="icon-button"
            onClick={() => setError("")}
            aria-label="Dismiss error"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
      <div className="workspace">
        <SessionSidebar
          sessions={sessions}
          selected={selected}
          connection={status.connection}
          onCreate={() => setCreate(true)}
          onSelect={(id) => {
            setSelected(id);
            setChat(undefined);
          }}
        />
        <ResourcePanel
          session={session}
          tab={tab}
          chats={chats}
          chat={chat}
          records={records}
          search={search}
          loading={resourceLoading}
          page={page}
          more={more}
          onPage={setPage}
          onManage={() => setManage(true)}
          onTab={setTab}
          onSearch={setSearch}
          onChat={setChat}
        />
        {session && chat ? (
          <Conversation
            key={session.id + chat.id}
            session={session}
            chat={chat}
            canSend={online === true && status.connection.role !== "viewer"}
            onBack={() => setChat(undefined)}
          />
        ) : (
          <section className="conversation-placeholder">
            <div className="empty-art">
              <Icon name="chat" size={60} />
              <span className="art-orbit one" />
              <span className="art-orbit two" />
            </div>
            <h2>Your conversations, connected</h2>
            <p>
              Select a conversation to read and reply.
              <br />
              Link a session to get started.
            </p>
            {session?.status !== "ready" && session && (
              <button className="primary" onClick={() => setManage(true)}>
                <Icon name="link" size={18} />
                Link WhatsApp
              </button>
            )}
          </section>
        )}
      </div>
      {settings && (
        <Dialog label="Gateway settings" onClose={() => setSettings(false)}>
          <ConnectionSettings
            status={status}
            onSaved={() => {
              setSettings(false);
              refresh();
            }}
            onClose={() => setSettings(false)}
          />
        </Dialog>
      )}
      {manage && session && (
        <SessionPanel
          session={session}
          canManage={status.connection.role !== "viewer"}
          onRefresh={refresh}
          onClose={() => setManage(false)}
        />
      )}
      {create && (
        <Dialog label="New WhatsApp session" onClose={() => setCreate(false)}>
          <form className="modal" onSubmit={newSession}>
            <div className="panel-heading">
              <h2>New WhatsApp session</h2>
              <button
                type="button"
                className="icon-button"
                onClick={() => setCreate(false)}
                aria-label="Close new session"
              >
                <Icon name="close" />
              </button>
            </div>
            <p className="muted">
              Give this WhatsApp account a name you will recognize.
            </p>
            <label>
              Session name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Support, Sales, Personal…"
                maxLength={100}
                required
                autoFocus
              />
            </label>
            <button className="primary wide" disabled={busy}>
              {busy ? "Creating…" : "Create and link session"}
            </button>
          </form>
        </Dialog>
      )}
    </main>
  );
}
