import { useEffect, useState, type MouseEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, Copy, ExternalLink, Globe2, LockKeyhole, RefreshCw } from 'lucide-react';
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState('');
  const [revision, refresh] = useState(0);
  const dirty = Boolean(status && (enabled !== status.enabled || access !== status.access));
  const locked = !status?.configured || busy || loading;

  function acceptStatus(value: Status) {
    setStatus(value); setEnabled(value.enabled); setAccess(value.access); setConfirmed(false);
  }
  function edit() { setConfirmed(false); setSaved(false); setError(''); }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setSaved(false); setCopyFeedback('');
    callBackend<Status>({ action: 'crm.external.status' }, AbortSignal.any([controller.signal, AbortSignal.timeout(20000)])).then(value => {
      if (!controller.signal.aborted) acceptStatus(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    const initialTheme = new URLSearchParams(window.location.search).get('maverick_theme');
    if (initialTheme === 'light' || initialTheme === 'dark') document.documentElement.dataset.theme = initialTheme;
    const message = (event: MessageEvent) => {
      if (!isExactMaverickParentMessage(event)) return;
      const theme = event.data?.type === 'maverick.shell.theme-changed'
        ? event.data.theme?.effective : event.data?.context?.content?.shell_theme?.effective;
      if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    };
    window.addEventListener('message', message);
    postToShell({ type: 'maverick.widget.ready', owner_app_id: 'crm', widget_id: 'crm-external-settings' });
    return () => window.removeEventListener('message', message);
  }, []);

  async function save() {
    if (!status || locked || !dirty || !confirmed) return;
    setBusy(true); setError(''); setSaved(false);
    try {
      const value = await callBackend<Status>({ action: 'crm.external.configure', enabled, access, expected_revision: status.revision, confirm: true }, AbortSignal.timeout(20000));
      acceptStatus(value); setSaved(true);
    } catch (cause) { setError((cause as Error).message); setConfirmed(false); }
    finally { setBusy(false); }
  }
  async function copyUrl() {
    if (!status?.url) return;
    try { await navigator.clipboard.writeText(status.url); setCopyFeedback('Link copiato'); }
    catch {
      // Isolated widgets have no clipboard-write delegation. Keep copying local
      // to this explicit click, without broadening the shell's browser policy.
      const focused = document.activeElement as HTMLElement | null;
      const field = document.createElement('textarea');
      field.value = status.url; field.readOnly = true;
      field.style.position = 'fixed'; field.style.opacity = '0';
      document.body.append(field); field.select();
      let copied = false;
      try { copied = document.execCommand('copy'); } catch { /* Manual selection remains available. */ }
      finally { field.remove(); focused?.focus(); }
      setCopyFeedback(copied ? 'Link copiato' : 'Copia non disponibile: seleziona il link.');
    }
  }
  function openPublicUrl(event: MouseEvent<HTMLAnchorElement>) {
    if (!status?.url || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (postToShell({
      type: 'maverick.app.external-url',
      owner_app_id: 'crm',
      widget_id: 'crm-external-settings',
      disposition: 'new-window',
      url: status.url,
    })) event.preventDefault();
  }

  const stateLabel = !status?.configured ? 'Da configurare' : !status.enabled ? 'Disattivato' : status.ready ? 'Servizio attivo' : 'In attesa del servizio';
  return <main className="crm-external-settings">
    <form onSubmit={event => { event.preventDefault(); void save(); }} aria-label="Pubblicazione CRM" aria-busy={busy || loading}>
      <div className="crm-external-content">
        <header className="crm-external-heading">
          <div><h1>CRM online</h1><p>Il tuo CRM, accessibile anche fuori da Maverick.</p></div>
          <button type="button" className="crm-external-icon" aria-label="Aggiorna stato" title={dirty ? 'Salva o annulla le modifiche prima di aggiornare' : 'Aggiorna stato'} disabled={busy || loading || dirty} onClick={() => refresh(value => value + 1)}>
            <RefreshCw size={17} aria-hidden="true" />
          </button>
        </header>
        {!status && loading && <p role="status">Caricamento impostazioni…</p>}
        {status && <>
          <section className="crm-external-address" aria-label="Indirizzo pubblico">
            <div className="crm-external-address-heading"><span><Globe2 size={16} aria-hidden="true" />Link pubblico</span>
              <span className={`crm-external-state ${status.enabled && status.ready ? 'is-active' : ''}`}><i aria-hidden="true" />{stateLabel}</span>
            </div>
            <div className="crm-external-link-row">
              <strong>{status.url || 'Dominio non configurato'}</strong>
              {status.url && <div className="crm-external-link-actions">
                <button type="button" className="crm-external-icon" aria-label="Copia link" title="Copia link" onClick={() => void copyUrl()}><Copy size={17} aria-hidden="true" /></button>
                {status.enabled && <a className="crm-external-icon" href={status.url} target="_blank" rel="noopener noreferrer" aria-label="Apri CRM" title="Apri CRM" onClick={openPublicUrl}><ExternalLink size={17} aria-hidden="true" /></a>}
              </div>}
            </div>
            {copyFeedback && <small role="status">{copyFeedback}</small>}
          </section>
          {!status.configured && <p className="crm-external-note">Configura il servizio pubblico e HTTPS per questa installazione. Il dominio sarà crm.apps.&lt;dominio-di-Maverick&gt;.</p>}
          <label className="crm-external-availability">
            <span><strong>Abilita il CRM pubblico</strong><small>Rendi disponibile la superficie al link indicato.</small></span>
            <input className="crm-external-switch" type="checkbox" role="switch" aria-label="Abilita il CRM pubblico" checked={enabled} disabled={locked} onChange={event => { setEnabled(event.target.checked); edit(); }} />
          </label>
          <fieldset className="crm-external-access" aria-describedby="crm-external-warning" disabled={locked || !enabled}>
            <legend>Accesso pubblico</legend>
            <div className="crm-external-access-options">
              <label><input type="radio" name="access" value="read-only" checked={access === 'read-only'} onChange={() => { setAccess('read-only'); edit(); }} />
                <span><strong>Sola lettura</strong><small>Visualizzazione ed esportazione dei dati.</small></span>
              </label>
              <label><input type="radio" name="access" value="read-write" checked={access === 'read-write'} onChange={() => { setAccess('read-write'); edit(); }} />
                <span><strong>Lettura e scrittura</strong><small>Anche creazione, modifica e cancellazione.</small></span>
              </label>
            </div>
          </fieldset>
          <p id="crm-external-warning" className={`crm-external-warning ${enabled && access === 'read-write' ? 'is-sensitive' : ''}`}>
            {enabled ? (access === 'read-write' ? 'Senza login: chiunque abbia il link può leggere, esportare, creare, modificare e cancellare i dati del CRM.' : 'Senza login: chiunque abbia il link può leggere ed esportare i dati del CRM. Nessuna modifica consentita.') : 'Il CRM pubblico non accetterà nuove richieste. I dati già scaricati non possono essere revocati.'}
          </p>
          <p className="crm-external-private"><LockKeyhole size={15} aria-hidden="true" /><span>Chat, API delle altre app e operazioni delle integrazioni restano private.</span></p>
        </>}
      </div>
      <footer className="crm-external-actions">
        {error && <p role="alert">{error}</p>}
        {dirty && <label className="crm-external-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} />
          <span>Ho verificato e confermo questa configurazione.</span>
        </label>}
        <div className="crm-external-action-row">
          <span className="crm-external-feedback" role="status">{busy ? 'Salvataggio…' : loading ? 'Verifica in corso…' : saved ? <><Check size={15} aria-hidden="true" />Configurazione salvata</> : dirty ? 'Modifiche non salvate' : status ? 'Nessuna modifica' : 'Stato non disponibile'}</span>
          {dirty && <button type="button" className="crm-external-cancel" disabled={busy} onClick={() => { if (status) acceptStatus(status); edit(); }}>Annulla</button>}
          <button type="submit" className="crm-external-save" disabled={locked || !dirty || !confirmed}>{busy ? 'Salvataggio…' : 'Salva modifiche'}</button>
        </div>
      </footer>
    </form>
  </main>;
}

createRoot(document.getElementById('root')!).render(<Settings />);
