import { useCallback, useRef, useState, type FormEvent } from "react";
import { operation, type Session } from "./api";
import { Icon } from "./Icons";
import { ConnectionSettings } from "./ConnectionSettings";
import { SessionPanel } from "./SessionPanel";
import { Workspace } from "./Workspace";
import { useMaverickHost } from "./host";
import { Dialog } from "./Dialog";
import { useWorkspace } from "./useWorkspace";

export function App() {
  const { status, sessions, selected, setSelected, error: connectionError, loading, refreshing, online, refresh } = useWorkspace();
  const [error, setError] = useState("");
  const [settings, setSettings] = useState(false);
  const [manage, setManage] = useState(false);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const creating = useRef(false);
  const [revision, setRevision] = useState(0);
  const session = sessions.find((s) => s.id === selected);
  const refreshAll = useCallback(() => {
    void refresh();
    setRevision((value) => value + 1);
  }, [refresh]);
  useMaverickHost(refreshAll, setSelected);
  async function newSession(e: FormEvent) {
    e.preventDefault();
    if (creating.current || online !== true || !name.trim()) return;
    creating.current = true;
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
      creating.current = false;
      setBusy(false);
    }
  }
  if (!status)
    return (
      <main className="setup-page">
        <div className="loading-card">
          <p role={loading ? "status" : "alert"}>{loading ? "Opening OpenWA…" : connectionError}</p>
          {!loading && <button onClick={refresh} disabled={refreshing}>Retry</button>}
        </div>
      </main>
    );
  if (!status.connection.configured || !status.connection.credential_available)
    return (
      <main className="setup-page">
        <ConnectionSettings status={status} onSaved={refresh} />
        {connectionError && <p className="error-banner" role="alert">{connectionError}</p>}
      </main>
    );
  return (
    <main className="app-shell">
      <header className="app-heading">
        <div className="app-identity">
          <span className="brand-icon">
            <Icon name="whatsapp" size={24} />
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
            onClick={refreshAll}
            disabled={refreshing}
            aria-label="Refresh"
          >
            <Icon name="refresh" />
          </button>
          {status.can_configure && (
            <button
              className="icon-button"
              onClick={() => setSettings(true)}
              disabled={busy}
              aria-label="Gateway settings"
            >
              <Icon name="settings" />
            </button>
          )}
        </div>
      </header>
      {connectionError && <div className="error-banner" role="alert">{connectionError}</div>}
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
      <Workspace key={JSON.stringify([status.send_scope, selected])}
        status={status} sessions={sessions} selected={selected} online={online === true}
        revision={revision} onSelect={setSelected} onCreate={() => setCreate(true)} onManage={() => setManage(true)} />
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
        <SessionPanel key={JSON.stringify([status.send_scope, session.id])}
          session={session}
          canManage={online === true && status.connection.role !== "viewer"}
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
            <button className="primary wide" disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create and link session"}
            </button>
          </form>
        </Dialog>
      )}
    </main>
  );
}
