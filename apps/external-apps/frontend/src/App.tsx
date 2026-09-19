import { useCallback, useEffect, useRef, useState } from 'react';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { appId, callBackend, label, type Detail, type Plan, type Publication } from './api';
import { PublicationDetail } from './PublicationDetail';
import { PrepareForm } from './PrepareForm';

export function App() {
  const [items, setItems] = useState<Publication[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<Detail>();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showPrepare, setShowPrepare] = useState(false);
  const [configured, setConfigured] = useState(true);
  const [domain, setDomain] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const epoch = useRef(0);
  const reads = useRef(0);
  const refresh = useCallback(() => setRefreshKey(v => v + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const current = epoch.current;
    const request = ++reads.current;
    setLoading(true); setDetail(undefined);
    Promise.all([
      callBackend<{ items: Publication[] }>({ action: 'list', query, status: filter, limit: 100 }, controller.signal),
      callBackend<{ status: string }>({ action: 'health' }, controller.signal),
      selected ? callBackend<Detail>({ action: 'get', external_app_id: selected }, controller.signal) : Promise.resolve(undefined),
    ]).then(([catalog, health, info]) => {
      if (epoch.current !== current || reads.current !== request) return;
      setItems(catalog.items); setConfigured(health.status === 'configured'); setDetail(info);
    }).catch(err => { if (!controller.signal.aborted && epoch.current === current && reads.current === request) setError(String(err.message)); })
      .finally(() => { if (epoch.current === current && reads.current === request) setLoading(false); });
    return () => controller.abort();
  }, [selected, query, filter, refreshKey]);

  useEffect(() => {
    window.parent.postMessage({ type: 'maverick.app.ready', app_id: appId }, '*');
    function message(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || !event.data) return;
      const data = event.data;
      if (data.type === 'maverick.app.data-changed' && data.owner_app_id === appId) refresh();
      if (data.type === 'maverick.shell.theme-changed' || data.type === 'maverick.app.navigate') {
        const theme = data.theme?.effective;
        if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
      }
      if (data.type === 'maverick.app.navigate' && (!data.app_id || data.app_id === appId)) {
        ++epoch.current; setDetail(undefined); setItems([]); setError(''); setNotice(''); setShowPrepare(false); setBusy(false); setQuery(''); setFilter('');
        setSelected(typeof data.params?.external_app_id === 'string' ? data.params.external_app_id : ''); refresh();
      }
    }
    window.addEventListener('message', message);
    return () => { ++epoch.current; window.removeEventListener('message', message); };
  }, [refresh]);

  async function mutate(body: Record<string, unknown>) {
    setBusy(true); setError(''); setNotice('');
    const current = epoch.current;
    try {
      const result = await callBackend<{ plan?: Plan; status?: string }>(body);
      if (epoch.current !== current) return;
      if (result.plan) { setSelected(result.plan.app_id); setShowPrepare(false); }
      setNotice(result.plan ? 'Piano preparato: controlla il dettaglio prima di approvare.' : `Operazione completata${result.status ? `: ${label(result.status)}` : ''}.`);
      refresh();
    } catch (err) { if (epoch.current === current) setError((err as Error).message); }
    finally { if (epoch.current === current) setBusy(false); }
  }

  async function publish(plan: Plan) {
    setBusy(true); setError(''); setNotice('');
    const current = epoch.current;
    try {
      await callBackend({ action: 'plan.approve', plan_id: plan.id, plan_digest: plan.plan_digest, confirm: true });
      if (epoch.current !== current) return;
      const result = await callBackend<{ status: string }>({ action: `${plan.kind}.apply`, plan_id: plan.id, plan_digest: plan.plan_digest, confirm: true, idempotency_key: crypto.randomUUID() });
      if (epoch.current === current) { setNotice(`Esito: ${label(result.status)}.`); refresh(); }
    } catch (err) { if (epoch.current === current) { setError((err as Error).message); refresh(); } }
    finally { if (epoch.current === current) setBusy(false); }
  }

  return <main className="app-shell">
    <header className="topbar"><div><p className="eyebrow">Maverick</p><h1>External Apps</h1><p className="muted">Pubblicazioni statiche, release immutabili.</p></div><div className="actions"><button className="secondary" onClick={refresh} disabled={busy}>Aggiorna</button><button onClick={() => setShowPrepare(v => !v)} disabled={!configured || busy}>Prepara pubblicazione</button></div></header>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!configured && <form className="setup" onSubmit={e => { e.preventDefault(); mutate({ action: 'deployment.configure', domain }); }}><h2>Configurazione richiesta</h2><p>L’amministratore deve predisporre wildcard DNS, TLS e listener separato. Questo campo non li crea.</p><label>Dominio pubblico<input required value={domain} onChange={e => setDomain(e.target.value)} placeholder="apps.example.com" /></label><button disabled={busy}>Salva dominio</button></form>}
    <div className="toolbar"><label className="search">Cerca<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Nome pubblicazione" /></label><label>Stato<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">Tutte le non archiviate</option>{['draft', 'published', 'suspended', 'archived'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label></div>
    <div className="layout"><section className="catalog" aria-label="Catalogo" aria-busy={loading}>
      {loading && !items.length ? <div className="skeleton" role="status">Caricamento pubblicazioni…</div> : items.length ? items.map(app => <button key={app.id} className={`catalog-row ${selected === app.id ? 'selected' : ''}`} aria-pressed={selected === app.id} onClick={() => setSelected(app.id)}><span><strong>{app.name}</strong><small>{app.managed_url}</small><small>HTTP: {label(app.health.status)}</small></span><span className={`badge ${app.status}`}>{label(app.status)}</span></button>) : <div className="empty"><h2>Nessuna pubblicazione</h2><p>Prepara una build Website Studio e crea il primo piano.</p></div>}
    </section><section className="workspace-detail">
      {showPrepare && <PrepareForm key={selected || 'new'} appId={selected || undefined} busy={busy} onPrepare={mutate} />}
      {detail ? <PublicationDetail detail={detail} busy={busy} onApprove={publish} onAction={action => mutate({ action, external_app_id: detail.app.id, ...(action === 'rollback.plan' ? {} : { expected_generation: detail.app.binding.generation, confirm: true, idempotency_key: crypto.randomUUID() }) })} /> : !showPrepare && <div className="empty">{selected && loading ? 'Caricamento dettaglio…' : 'Seleziona una pubblicazione per vedere release e operazioni.'}</div>}
      {selected && !showPrepare && <button className="quiet" onClick={() => setSelected('')}>Deseleziona / nuova app</button>}
    </section></div>
  </main>;
}
