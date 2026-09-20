import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { callBackend } from '../api';
import { postToShell } from '../domain/shellMessaging';
import '../styles.css';
import './settings.css';

type Status = { configured: boolean; enabled: boolean; ready: boolean; url?: string; access: 'read-only' | 'read-write'; revision: number };

function Settings() {
  const [status, setStatus] = useState<Status>();
  const [enabled, setEnabled] = useState(false);
  const [access, setAccess] = useState<Status['access']>('read-only');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [revision, refresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    callBackend<Status>({ action: 'crm.external.status' }, AbortSignal.any([controller.signal, AbortSignal.timeout(20000)])).then(value => {
      setStatus(value); setEnabled(value.enabled); setAccess(value.access); setConfirmed(false);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    const message = (event: MessageEvent) => {
      if (!isExactMaverickParentMessage(event)) return;
      const theme = event.data?.context?.content?.shell_theme?.effective;
      if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    };
    window.addEventListener('message', message);
    postToShell({ type: 'maverick.widget.ready', owner_app_id: 'crm', widget_id: 'crm-external-settings' });
    return () => { controller.abort(); window.removeEventListener('message', message); };
  }, [revision]);

  async function save() {
    if (!status) return;
    setBusy(true); setError('');
    try {
      const value = await callBackend<Status>({ action: 'crm.external.configure', enabled, access, expected_revision: status.revision, confirm: true }, AbortSignal.timeout(20000));
      setStatus(value); setConfirmed(false);
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }
  return <main className="crm-external-settings">
    <header><h1>CRM online</h1><p>L’interfaccia completa e i dati del CRM, sul dominio di questa installazione. Chat e API delle altre app non vengono pubblicate.</p></header>
    {error && <p role="alert">{error}</p>}
    {!status && !error && <p role="status">Caricamento impostazioni…</p>}
    {status && <>
      <div className="crm-external-address"><strong>{status.url || 'Dominio non configurato'}</strong>
        <span>{!status.enabled ? 'Disabilitato' : status.ready ? 'Servizio attivo · verifica HTTPS aprendo il link' : 'Abilitato · in attesa del servizio'}</span>
        {status.url && status.enabled && <a href={status.url} target="_blank" rel="noopener noreferrer">Apri CRM ↗</a>}
      </div>
      {!status.configured && <p>Occorre configurare il servizio pubblico e HTTPS per questa installazione. Il dominio viene derivato automaticamente: crm.apps.&lt;dominio-di-Maverick&gt;.</p>}
      <form onSubmit={event => { event.preventDefault(); void save(); }}>
        <label><input type="checkbox" checked={enabled} disabled={!status.configured || busy} onChange={event => { setEnabled(event.target.checked); setConfirmed(false); }} /> Abilita il CRM pubblico</label>
        <label>Accesso pubblico<select value={access} disabled={!status.configured || busy} onChange={event => { setAccess(event.target.value as Status['access']); setConfirmed(false); }}>
          <option value="read-only">Sola lettura</option><option value="read-write">Lettura, creazione, modifica e cancellazione</option>
        </select></label>
        <p className="crm-external-warning">{enabled ? (access === 'read-write' ? 'Chiunque abbia il link potrà leggere, esportare, creare, modificare e cancellare dati del CRM, senza login.' : 'Chiunque abbia il link potrà leggere ed esportare i dati del CRM, senza login. Le modifiche saranno bloccate.') : 'Disabilitando la superficie, le nuove richieste pubbliche saranno bloccate. I dati già scaricati non possono essere revocati.'}</p>
        <p>Le operazioni delle integrazioni Mail, Calendar, Storage e Speech restano disponibili solo dentro Maverick.</p>
        <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} /> Ho verificato e confermo questa configurazione.</label>
        <button type="submit" disabled={!status.configured || !confirmed || busy}>{busy ? 'Salvataggio…' : 'Salva configurazione'}</button>
      </form>
    </>}
    <button type="button" onClick={() => refresh(value => value + 1)} disabled={busy}>Aggiorna stato</button>
  </main>;
}

createRoot(document.getElementById('root')!).render(<Settings />);
