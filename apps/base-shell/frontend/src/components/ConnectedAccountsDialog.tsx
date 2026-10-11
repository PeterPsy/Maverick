import { useEffect, useRef, useState } from "react";
import { connectedAccounts, disconnectConnectedAccount, selectConnectedAccount, setConnectedAppAccess, setConnectedWorkspaceAccess, startGoogle,
  type ConnectedAccountsPayload, type GoogleService } from "../api";
import { GoogleMark, GoogleServices, googleCallbackMessage } from "./GoogleServices";
import { GoogleAuthError } from "../lib/googleAuth";

export function ConnectedAccountsDialog({ onClose, onChanged, callbackError = null }: {
  onClose: () => void; onChanged: () => void; callbackError?: string | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  const googleController = useRef<AbortController | null>(null);
  const [data, setData] = useState<ConnectedAccountsPayload | null>(null);
  const [services, setServices] = useState<GoogleService[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(googleCallbackMessage(callbackError));
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(null);

  useEffect(() => {
    alive.current = true;
    dialog.current?.showModal();
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

  function close() { googleController.current?.abort(); dialog.current?.close(); onClose(); }

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

  async function connect() {
    if (busy) return;
    const controller = new AbortController(); googleController.current = controller;
    setBusy(true); setError(null); setNotice("Continue in your browser. Maverick will update automatically.");
    try {
      if (await startGoogle("connect", services, controller.signal) === "completed" && alive.current) {
        onChanged();
        const result = await connectedAccounts(controller.signal);
        if (alive.current) { setData(result); setNotice("Google connected."); setBusy(false); }
      }
    } catch (error) {
      if (alive.current && !controller.signal.aborted) {
        setBusy(false); setNotice(null);
        setError(error instanceof GoogleAuthError ? googleCallbackMessage(error.code) : "Unable to complete the Google connection. Please try again.");
      }
    } finally { if (googleController.current === controller) googleController.current = null; }
  }

  return <dialog ref={dialog} className="bs-connected-accounts" aria-labelledby="bs-accounts-title"
    onCancel={event => { event.preventDefault(); close(); }}>
    <header><div><p>Personal settings</p><h2 id="bs-accounts-title">Connected accounts</h2></div>
      <button type="button" aria-label="Close connected accounts" onClick={close} autoFocus><span className="material-symbols-rounded" aria-hidden="true">close</span></button></header>
    <div className="bs-connected-accounts__body">
      <p>Choose which personal Google accounts apps can use in this workspace. Each workspace has its own selection.</p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {!data && !error && <p role="status">Loading accounts…</p>}
      {data && <>
        {data.items.map(account => <section key={account.account_id} className="bs-connected-accounts__account">
          <div><strong>{account.display_name}</strong><small>{account.email}</small><small>{account.status === "connected"
            ? (account.services.length ? account.services.join(" · ") : "Google sign-in only") : "Reconnect required"}</small></div>
          <div className="bs-connected-accounts__actions">
            <label className="bs-connected-accounts__workspace-access">
              <input type="checkbox" aria-label={`Use ${account.email} in this workspace`}
                checked={data.selection?.account_ids.includes(account.account_id) ?? false}
                disabled={busy || (account.status !== "connected" && !data.selection?.account_ids.includes(account.account_id))}
                onChange={event => void mutate(() => setConnectedWorkspaceAccess(data.workspace_id, account.account_id, event.target.checked))} />
              Use in this workspace
            </label>
            {data.selection?.account_ids.includes(account.account_id) && (data.selection.account_id === account.account_id
              ? <span>Default account</span>
              : <button type="button" disabled={busy || account.status !== "connected"} onClick={() => void mutate(() => selectConnectedAccount(data.workspace_id, account.account_id))}>Make default</button>)}
            {account.status === "connected" && <button type="button" disabled={busy} onClick={() => setConfirmDisconnect(account.account_id)}>Disconnect</button>}
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
        {data.selection && data.apps.length > 0 && <section>
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
        <section>
          <GoogleServices selected={services} onChange={setServices} disabled={busy || !data.google.configured} />
          <button className="bs-google-button" type="button" disabled={busy || !data.google.configured} onClick={() => void connect()}>
            <GoogleMark /><span>{busy ? "Connecting…" : data.items.length ? "Update permissions or add an account" : "Connect Google"}</span>
          </button>
          {busy && googleController.current && <button type="button" onClick={() => {
            googleController.current?.abort(); setBusy(false); setNotice(null); setError("Google connection cancelled. You can try again.");
          }}>Cancel connection</button>}
          {!data.google.configured && <p>Google sign-in is not configured on this installation. Your administrator must configure the Google connection.</p>}
        </section>
      </>}
    </div>
  </dialog>;
}
