import { requestParentExternalUrl } from '@maverick/pwa-cache';
import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { copyPublicUrl, date, label, type Detail, type Plan } from './api';

type Props = { detail: Detail; busy: boolean; onApprove: (plan: Plan) => void; onAction: (action: string) => void };
export function PublicationDetail({ detail, busy, onApprove, onAction }: Props) {
  const [consent, setConsent] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const app = detail.app;
  const plan = detail.plans.find(p => p.status === 'ready' && p.expires * 1000 > Date.now());
  useEffect(() => { setConsent(false); setCopied(false); setCopyFailed(false); }, [app.id, plan?.id]);
  useEffect(() => {
    if (confirmation) dialog.current?.showModal();
    else dialog.current?.close();
  }, [confirmation]);
  return <article className="detail" aria-label="Dettaglio pubblicazione">
    <header><div><p className="eyebrow">Pubblicazione</p><h2>{app.name}</h2></div><span className={`badge ${app.status}`}>{label(app.status)}</span></header>
    <a className="public-url" href={app.managed_url} onClick={(event) => openExternalLink(event, app.managed_url)} target="_blank" rel="noopener noreferrer">{app.managed_url}</a>
    <button className="quiet" onClick={async () => { const ok = await copyPublicUrl(app.managed_url); setCopied(ok); setCopyFailed(!ok); }}>{copied ? 'URL copiato' : 'Copia URL'}</button>
    {copyFailed && <p role="status">Copia non consentita dal browser: seleziona e copia il collegamento.</p>}
    <dl>
      <dt>Sorgente</dt><dd>{app.provider_id} · {app.source_id}</dd>
      <dt>Release corrente</dt><dd>{app.binding.current?.release_id || 'Nessuna'}</dd>
      <dt>Release precedente</dt><dd>{app.binding.previous?.release_id || 'Nessuna'}</dd>
      <dt>Verifica HTTP</dt><dd>{label(app.health.status)} · {date(app.health.checked_at)}</dd>
      {app.binding.current && <><dt>Digest</dt><dd className="mono">{app.binding.current.digest}</dd></>}
    </dl>
    {app.last_error_code && <p role="status" className="error">Ultimo errore: {app.last_error_code}</p>}
    {plan && <section className="plan" aria-label="Piano da approvare">
      <h3>{plan.kind === 'rollback' ? 'Conferma ripristino' : 'Conferma pubblicazione'}</h3>
      <p>Revisione <code>{plan.source_revision}</code></p>
      <p>{plan.release?.file_count} file · {Math.ceil((plan.release?.size_bytes || 0) / 1024)} KiB · scade {date(plan.expires)}</p>
      <p className="mono">SHA-256: {plan.release?.digest}</p>
      <p>Sostituisce: <code>{plan.will_replace_release_id || 'prima pubblicazione'}</code></p>
      <label className="consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={busy} /><span>Ho verificato URL e contenuti. Tutti i file saranno pubblici; l’URL non protegge l’accesso.</span></label>
      <button disabled={!consent || busy} onClick={() => onApprove(plan)}>Approva e {plan.kind === 'rollback' ? 'ripristina' : 'pubblica'}</button>
    </section>}
    {detail.plans[0]?.status === 'preparing' && <p role="status">Preparazione export in corso. Aggiorna tra pochi secondi.</p>}
    {detail.plans[0]?.status === 'failed' && <p className="error">Export non disponibile: {detail.plans[0].error_code}</p>}
    <div className="actions">
      <button className="secondary" disabled={busy || !app.binding.enabled} onClick={() => setConfirmation('suspend')}>Sospendi</button>
      <button className="secondary" disabled={busy || app.binding.archived || (!app.binding.previous && app.binding.enabled) || !app.binding.current} onClick={() => onAction('rollback.plan')}>Prepara rollback</button>
      <button className="secondary danger" disabled={busy || app.binding.archived} onClick={() => setConfirmation('archive')}>Archivia</button>
    </div>
    <h3>Cronologia</h3>
    {detail.history.length ? <ol className="history">{detail.history.map((event, i) => <li key={`${event.created}-${i}`}><strong>{event.action}</strong><small>{date(event.created)}</small>{event.detail && <span>{event.detail}</span>}</li>)}</ol> : <p className="muted">Nessuna operazione.</p>}
    <dialog ref={dialog} onCancel={() => setConfirmation('')} aria-labelledby="confirm-title">
      <h3 id="confirm-title">{confirmation === 'archive' ? 'Archiviare questa app?' : 'Sospendere questa app?'}</h3>
      <p>Le nuove richieste saranno bloccate. Release e cronologia verranno conservate.</p>
      <div className="actions"><button className="secondary" autoFocus onClick={() => setConfirmation('')}>Annulla</button><button onClick={() => { onAction(confirmation); setConfirmation(''); }}>Conferma</button></div>
    </dialog>
  </article>;
}

function openExternalLink(event: MouseEvent<HTMLAnchorElement>, url: string) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  if (requestParentExternalUrl(url)) event.preventDefault();
}
