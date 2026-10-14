import { useEffect, useRef, useState } from "react";
import { getServerProfiles, removeServerProfile, saveServerProfile, switchServerProfile, type ServerProfile, type ServerProfiles } from "../lib/serverProfiles";

export function ServerProfilesPanel({ beforeSwitch }: { beforeSwitch?: () => void }) {
  const [data, setData] = useState<ServerProfiles | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [origin, setOrigin] = useState("");
  const [editing, setEditing] = useState<ServerProfile | null>(null);
  const [removing, setRemoving] = useState<ServerProfile | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    void getServerProfiles().then(result => { if (alive.current) setData(result); }).catch(reason => { if (alive.current) setError(String(reason.message || reason)); });
    return () => { alive.current = false; };
  }, []);
  async function run(action: () => Promise<ServerProfiles | void>) {
    if (busy) return;
    setBusy(true); setError(null);
    try { const result = await action(); if (result && alive.current) setData(result); }
    catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { if (alive.current) setBusy(false); }
  }
  return <section className="bs-account-section" aria-labelledby="bs-servers-heading">
    <div><h3 id="bs-servers-heading">Saved connections</h3><p>{data?.native
      ? "Saved on this device. Each server has its own login, workspaces and data."
      : "Open another Loopino installation in this browser. Bookmarks are saved for this site; each installation has its own login."}</p></div>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">Loading servers…</p>}
    {data?.profiles.map(profile => <article className={`bs-connected-accounts__account bs-server-card${profile.current ? " is-current" : ""}`} key={profile.id}>
      <div className="bs-server-card__heading"><span className="material-symbols-rounded" aria-hidden="true">dns</span><div><strong>{profile.name}</strong><small>{profile.origin}</small></div>{profile.current && <span className="bs-server-card__badge">Current server</span>}</div>
      <div className="bs-connected-accounts__actions">
        {!profile.current && <button type="button" disabled={busy} onClick={() => void run(async () => { beforeSwitch?.(); await switchServerProfile(profile); })}>{data.native ? "Switch server" : "Open server"}</button>}
        {(data.native || !profile.current) && <button type="button" disabled={busy} onClick={() => { setEditing(profile); setName(profile.name); setOrigin(profile.origin); }}>Rename</button>}
        {!profile.current && <button type="button" disabled={busy} onClick={() => setRemoving(profile)}>Remove</button>}
      </div>
      {removing?.id === profile.id && <div className="bs-connected-accounts__confirmation"><p>{data.native
        ? `Remove ${profile.name} from this device? Its saved login on this device will be cleared. Data on the server will remain available.`
        : `Remove the bookmark for ${profile.name}? Its browser login and server data will remain available.`}</p>
        <button type="button" disabled={busy} onClick={() => void run(async () => { const next = await removeServerProfile(profile.id); setRemoving(null); return next; })}>Remove server</button>
        <button type="button" disabled={busy} onClick={() => setRemoving(null)}>Cancel</button></div>}
    </article>)}
    {data && <form className="bs-server-form" onSubmit={event => { event.preventDefault(); void run(async () => {
      const next = await saveServerProfile(name, origin, editing?.id); setEditing(null); setName(""); setOrigin(""); return next;
    }); }}>
      <h3>{editing ? "Rename server" : "Add server"}</h3>
      <label>Name<input required maxLength={80} value={name} disabled={busy} onChange={event => setName(event.target.value)} autoComplete="off" /></label>
      <label>Server address<input required type="url" placeholder="https://loopino.example.com" value={origin} disabled={busy || !!editing} onChange={event => setOrigin(event.target.value)} autoCapitalize="none" autoComplete="url" /></label>
      <div className="bs-connected-accounts__actions"><button type="submit" disabled={busy}>{editing ? "Save name" : "Add server"}</button>
        {editing && <button type="button" disabled={busy} onClick={() => { setEditing(null); setName(""); setOrigin(""); }}>Cancel</button>}</div>
    </form>}
    <p className="bs-account-note">Switching stops device activity on the current server. Background tasks on that server may continue. Server data is kept separate.</p>
    {busy && <p role="status">Checking server or updating profiles…</p>}
  </section>;
}

export function ServerProfilesLauncher({ beforeSwitch, inline = false }: { beforeSwitch?: () => void; inline?: boolean }) {
  const [open, setOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) launcher.current?.focus();
    wasOpen.current = open;
  }, [open]);
  return <><button ref={launcher} type="button" className={inline ? "bs-login__server" : "bs-server-launcher"}
    aria-label={inline ? `Change server (${window.location.host})` : undefined} aria-haspopup="dialog" aria-expanded={open}
    onClick={() => setOpen(true)}><span className="material-symbols-rounded" aria-hidden="true">dns</span>{inline ? window.location.host : " Servers"}</button>
    {open && <ServerProfilesDialog onClose={() => setOpen(false)} beforeSwitch={beforeSwitch} />}</>;
}

function ServerProfilesDialog({ onClose, beforeSwitch }: { onClose: () => void; beforeSwitch?: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
    heading.current?.focus();
    return () => dialog.current?.close();
  }, []);
  return <dialog ref={dialog} className="bs-connected-accounts bs-connected-accounts--servers" aria-label="Servers" onCancel={event => { event.preventDefault(); onClose(); }}>
    <header><div className="bs-server-dialog-heading"><span className="material-symbols-rounded" aria-hidden="true">dns</span><div><h2 ref={heading} tabIndex={-1}>Servers</h2><p>Choose where you connect.</p></div></div><button className="bs-connected-accounts__close" aria-label="Close servers" onClick={onClose}><span className="material-symbols-rounded" aria-hidden="true">close</span></button></header>
    <div className="bs-connected-accounts__body"><ServerProfilesPanel beforeSwitch={beforeSwitch} /></div>
  </dialog>;
}
