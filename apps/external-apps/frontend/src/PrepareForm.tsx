import { useState, type FormEvent } from 'react';
export function PrepareForm({ busy, appId, onPrepare }: { busy: boolean; appId?: string; onPrepare: (body: Record<string, unknown>) => void }) {
  const [name, setName] = useState('');
  const [site, setSite] = useState('');
  const [build, setBuild] = useState('');
  const [format, setFormat] = useState('static_bundle');
  function submit(event: FormEvent) {
    event.preventDefault();
    onPrepare({ action: 'publish.plan', ...(appId ? { external_app_id: appId } : {}), name, source_entity_id: site, build_id: build, format });
  }
  return <form className="prepare-form" onSubmit={submit}>
    <h3>{appId ? 'Nuova release' : 'Nuova pubblicazione'}</h3>
    <p className="muted">Usa una build completata in Website Studio. La preparazione non pubblica nulla.</p>
    <label>Nome<input required value={name} onChange={e => setName(e.target.value)} maxLength={120} placeholder="Nome del sito" /></label>
    <label>Site ID<input required value={site} onChange={e => setSite(e.target.value)} maxLength={128} placeholder="site_…" /></label>
    <label>Build ID<input required value={build} onChange={e => setBuild(e.target.value)} maxLength={128} placeholder="build_…" /></label>
    <label>Routing<select value={format} onChange={e => setFormat(e.target.value)}><option value="static_bundle">Statico</option><option value="spa_bundle">SPA</option></select></label>
    <button disabled={busy}>Prepara piano</button>
  </form>;
}
