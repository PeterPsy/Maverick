import { useEffect, useRef, useState } from "react";
import { AccountAvatar } from '@maverick/account-avatar';
import { connectedAccounts, disconnectConnectedAccount, selectConnectedAccount, setConnectedAppAccess, setConnectedWorkspaceAccess, startGoogle,
  type ConnectedAccountsPayload, type GoogleService, type SessionUser } from "../api";
import { GoogleMark, GoogleServices, googleCallbackMessage } from "./GoogleServices";
import { GoogleAuthError } from "../lib/googleAuth";
import { UserAvatar } from "./UserAvatar";
import { ServerProfilesPanel } from "./ServerProfilesPanel";

type Section = "profile" | "google" | "access" | "servers" | "logout";
const sections: { id: Section; label: string; icon: string }[] = [
  { id: "profile", label: "Profile", icon: "person" },
  { id: "google", label: "Connected accounts", icon: "link" },
  { id: "access", label: "App access", icon: "shield" },
  { id: "servers", label: "Servers", icon: "dns" },
];

export function ConnectedAccountsDialog({ onClose, onChanged, callbackError = null, user, workspaceName, onLogout, onOpenSettings, initialSection }: {
  onClose: () => void; onChanged: () => void; callbackError?: string | null;
  user?: SessionUser; workspaceName?: string; onLogout?: () => Promise<void>; onOpenSettings?: () => void; initialSection?: Section;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const alive = useRef(true);
  const googleController = useRef<AbortController | null>(null);
  const [data, setData] = useState<ConnectedAccountsPayload | null>(null);
  const [services, setServices] = useState<GoogleService[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(googleCallbackMessage(callbackError));
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(null);
  const preferenceKey = `maverick.account-panel.v1.${user?.user_id ?? "anonymous"}`;
  const [section, setSection] = useState<Section>(() => {
    if (callbackError) return "google";
    if (initialSection) return initialSection;
    try { const saved = localStorage.getItem(preferenceKey); if (sections.some(item => item.id === saved)) return saved as Section; } catch { /* Preferences are optional. */ }
    return user ? "profile" : "google";
  });
  function navigate(next: Section) {
    setSection(next); setConfirmDisconnect(null);
    if (next !== "logout") try { localStorage.setItem(preferenceKey, next); } catch { /* Preferences are optional. */ }
  }

  useEffect(() => {
    alive.current = true;
    dialog.current?.showModal();
    title.current?.focus({ preventScroll: true });
    const controller = new AbortController();
    connectedAccounts(controller.signal).then(result => {
      if (alive.current) { setData(result); setServices(result.items.find(item => item.account_id === result.selection?.account_id)?.services ?? []); }
    }).catch(() => { if (!controller.signal.aborted) setError("Unable to load connected accounts. Please reopen this panel to try again."); });
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted && !googleController.current) {
        setBusy(false); setNotice(null);
        void connectedAccounts(controller.signal).then(setData).catch(() => {});
      }
    };
    window.addEventListener("pageshow", restore);
    return () => { alive.current = false; controller.abort(); googleController.current?.abort(); window.removeEventListener("pageshow", restore); dialog.current?.close(); };
  }, []);

  function cancelGoogle() {
    const controller = googleController.current;
    if (!controller) return;
    googleController.current = null;
    controller.abort();
    setBusy(false); setNotice(null);
  }

  function close() { cancelGoogle(); dialog.current?.close(); onClose(); }

  async function mutate(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await action();
      if (!alive.current) return;
      onChanged();
      const result = await connectedAccounts();
      if (alive.current) setData(result);
    } catch { if (alive.current) setError("Unable to update the Google connection. Please try again."); }
    finally { if (alive.current) setBusy(false); }
  }

  async function connect(selectedServices = services) {
    if (busy) return;
    const controller = new AbortController(); googleController.current = controller;
    setBusy(true); setError(null); setNotice("Continue in your browser. Maverick will update automatically.");
    try {
      if (await startGoogle("connect", selectedServices, controller.signal) === "completed"
          && alive.current && googleController.current === controller && !controller.signal.aborted) {
        onChanged();
        const result = await connectedAccounts(controller.signal);
        if (alive.current && googleController.current === controller && !controller.signal.aborted) {
          setData(result); setNotice("Google connected."); setBusy(false);
        }
      }
    } catch (error) {
      if (alive.current && googleController.current === controller && !controller.signal.aborted) {
        setBusy(false); setNotice(null);
        setError(error instanceof GoogleAuthError ? googleCallbackMessage(error.code) : "Unable to complete the Google connection. Please try again.");
      }
    } finally { if (googleController.current === controller) googleController.current = null; }
  }

  return <dialog ref={dialog} className="bs-connected-accounts" aria-labelledby="bs-accounts-title"
    onCancel={event => { event.preventDefault(); close(); }}>
    <header><div className="bs-account-heading"><UserAvatar user={user} size={44} /><div><p>{user?.email || user?.username || "Personal settings"}</p><h2 ref={title} id="bs-accounts-title" tabIndex={-1}>Account and servers</h2></div></div>
      <button type="button" className="bs-connected-accounts__close" aria-label="Close account panel" onClick={close}><span className="material-symbols-rounded" aria-hidden="true">close</span></button></header>
    <div className="bs-account-layout">
      <nav className="bs-account-nav" aria-label="Account settings">
        {sections.map(item => <button type="button" key={item.id} aria-current={section === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><span className="material-symbols-rounded" aria-hidden="true">{item.icon}</span>{item.label}</button>)}
        {onOpenSettings && <button type="button" onClick={() => { close(); onOpenSettings(); }}><span className="material-symbols-rounded" aria-hidden="true">settings</span>Settings<span className="material-symbols-rounded bs-account-nav__arrow" aria-hidden="true">arrow_outward</span></button>}
        {onLogout && <button type="button" className="bs-account-nav__logout" aria-current={section === "logout" ? "page" : undefined} onClick={() => navigate("logout")}><span className="material-symbols-rounded" aria-hidden="true">logout</span>Log out</button>}
      </nav>
    <div className="bs-connected-accounts__body">
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {section === "profile" && <section className="bs-account-section"><h3>Your profile</h3><div className="bs-account-profile"><UserAvatar user={user} size={64} /><div><strong>{user?.display_name || user?.username || "Maverick user"}</strong><small>{user?.email || user?.username}</small></div></div>
        <dl className="bs-account-details"><div><dt>Server</dt><dd>{window.location.origin}</dd></div><div><dt>Workspace</dt><dd>{workspaceName || data?.workspace_id || "—"}</dd></div><div><dt>Role</dt><dd>{user?.platform_role || "member"}</dd></div></dl>
        <p className="bs-account-note">This is your signed-in Maverick identity. Connecting another Google account for an app keeps this profile.</p>
      </section>}
      {section === "servers" && <ServerProfilesPanel beforeSwitch={() => { cancelGoogle(); setNotice(null); }} />}
      {section === "logout" && <section className="bs-account-section"><h3>Log out of this server</h3><p>End your Maverick session on {window.location.host}. Google connections stay linked and your sessions on other servers stay available.</p>
        <div className="bs-connected-accounts__actions"><button type="button" disabled={busy && !googleController.current} onClick={() => {
          cancelGoogle(); setBusy(true); setError(null);
          void onLogout?.().catch(() => { if (alive.current) { setBusy(false); setError("Unable to confirm logout. Please try again."); } });
        }}>Log out of this server</button><button type="button" onClick={() => navigate("profile")}>Cancel</button></div></section>}
      {(section === "google" || section === "access") && <><div><h3>{section === "google" ? "Connected accounts" : "App access"}</h3><p>{section === "google"
        ? "Link personal Google accounts and choose the services they provide. Connections belong to your Maverick identity on this server."
        : `Choose accounts and permissions for ${workspaceName || data?.workspace_id || "this workspace"}. Each workspace has its own selection.`}</p></div>
      {!data && !error && <p role="status">Loading accounts…</p>}
      {data && <>
        {data.items.map(account => <section key={account.account_id} className="bs-connected-accounts__account">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <AccountAvatar pictureUrl={account.picture_url} size={36} fallback={<GoogleMark />} />
            <div><strong>{account.email || account.display_name}</strong>{account.display_name && account.display_name !== account.email && <small>{account.display_name}</small>}<small>{account.status === "connected"
              ? (account.services.length ? account.services.join(" · ") : "Google sign-in only") : "Reconnect required"}</small></div>
          </div>
          <div className="bs-connected-accounts__actions">
            {section === "access" && <><label className="bs-connected-accounts__workspace-access">
              <input type="checkbox" aria-label={`Use ${account.email} in this workspace`}
                checked={data.selection?.account_ids.includes(account.account_id) ?? false}
                disabled={busy || (account.status !== "connected" && !data.selection?.account_ids.includes(account.account_id))}
                onChange={event => void mutate(() => setConnectedWorkspaceAccess(data.workspace_id, account.account_id, event.target.checked))} />
              Use in this workspace
            </label>
            {data.selection?.account_ids.includes(account.account_id) && (data.selection.account_id === account.account_id
              ? <span>Default account</span>
              : <button type="button" disabled={busy || account.status !== "connected"} onClick={() => void mutate(() => selectConnectedAccount(data.workspace_id, account.account_id))}>Make default</button>)}</>}
            {section === "google" && (account.status === "connected" ? <button type="button" disabled={busy} onClick={() => setConfirmDisconnect(account.account_id)}>Disconnect</button>
              : <button type="button" disabled={busy || !data.google.configured} onClick={() => { setServices(account.services); void connect(account.services); }}>Reconnect</button>)}
          </div>
          {confirmDisconnect === account.account_id && <div className="bs-connected-accounts__confirmation">
            <p>Disconnect {account.email} from Maverick in all workspaces? Maverick will also ask Google to revoke permissions for this connection.</p>
            <button type="button" disabled={busy} onClick={() => void mutate(async () => {
              const result = await disconnectConnectedAccount(account.account_id);
              if (alive.current) { setConfirmDisconnect(null); setNotice(result.revoked_at_google ? "Google disconnected." : "Disconnected from Maverick. Revocation at Google could not be confirmed."); }
            })}>Disconnect Google</button>
            <button type="button" disabled={busy} onClick={() => setConfirmDisconnect(null)}>Cancel</button>
          </div>}
        </section>)}
        {section === "access" && data.selection && data.apps.length > 0 && <section>
          <h3>Apps using workspace accounts</h3>
          {data.apps.map(app => {
            const selected = data.items.filter(item => data.selection?.account_ids.includes(item.account_id) && item.status === "connected");
            const available = selected.filter(item => app.services.some(service => item.services.includes(service)));
            const missing = app.services.filter(service => !selected.some(item => item.services.includes(service)));
            return <label className="bs-connected-accounts__app" key={app.app_id}>
              <span><strong>{app.name}</strong><small>{available.length ? `${available.length} account${available.length === 1 ? "" : "s"} available · ${app.services.join(" · ")}`
                : selected.length ? `Additional consent needed: ${missing.join(", ")}` : "Select an account with the required Google permissions"}</small></span>
              <input aria-label={`Allow ${app.name} to use Google`} type="checkbox" disabled={busy}
                checked={!data.selection!.disabled_apps.includes(app.app_id)}
                onChange={event => void mutate(() => setConnectedAppAccess(data.workspace_id, app.app_id, event.target.checked))} />
            </label>;
          })}
        </section>}
        {section === "google" && <section>
          <GoogleServices selected={services} onChange={setServices} disabled={busy || !data.google.configured} />
          <button className="bs-google-button" type="button" disabled={busy || !data.google.configured} onClick={() => void connect()}>
            <GoogleMark /><span>{busy ? "Connecting…" : data.items.length ? "Update permissions or add an account" : "Connect Google"}</span>
          </button>
          {busy && googleController.current && <button type="button" onClick={() => {
            cancelGoogle(); setError("Google connection cancelled. You can try again.");
          }}>Cancel connection</button>}
          {!data.google.configured && <p>Google sign-in is not configured on this installation. Your administrator must configure the Google connection.</p>}
        </section>}
      </>}
      </>}
    </div>
    </div>
  </dialog>;
}
