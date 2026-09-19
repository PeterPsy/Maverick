import { FormEvent, useState } from 'react';
import { ProviderReference, completedOperation } from '../domain/integrations';
import { Provider, Selection } from '../domain/vnext';

export function ProviderBrowser({ selected, providers, refresh }: { selected: Selection; providers: Provider[]; refresh: () => void }) {
  const [alias, setAlias] = useState('mail');
  const [results, setResults] = useState<ProviderReference[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const target = { entity_type: selected.entity, entity_id: selected.record.id };
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    setBusy(true); setError(''); setResults([]);
    try {
      const op = await completedOperation({ action: 'crm.integration_search', ...target, provider_alias: alias, query: form.get('query') });
      setResults(op.result.references || []);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Provider search failed.'); }
    finally { setBusy(false); }
  }
  async function link(ref: ProviderReference) {
    setBusy(true); setError('');
    try { await completedOperation({ action: 'crm.integration_link', ...target, provider_alias: alias, source_entity_type: ref.source_entity_type, source_entity_id: ref.source_entity_id }); refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to verify this reference.'); }
    finally { setBusy(false); }
  }
  return <details className="vn-provider-browser"><summary>Find and connect app records</summary>
    <form onSubmit={(event) => void search(event)}><label>Search provider<select aria-label="Search provider" value={alias} onChange={(event) => { setAlias(event.target.value); setResults([]); }}>{['mail', 'calendar', 'files', 'tasks'].map((value) => <option key={value} value={value} disabled={!providers.some((p) => p.alias === value && p.configured)}>{value}</option>)}</select></label>
    <label>Search linked context<input name="query" defaultValue={String(selected.record.email || selected.record.name || selected.record.display_name || '')} maxLength={300} /></label><button disabled={busy}>{busy ? 'Searching…' : 'Search provider'}</button></form>
    {error ? <p role="alert" className="crm-alert">{error}</p> : null}
    {results.map((ref) => <div className="vn-linked-row" key={`${ref.source_entity_type}:${ref.source_entity_id}`}><div><strong>{ref.title}</strong><p className="vn-hint">{ref.source_entity_type} · {ref.summary}</p></div><button disabled={busy} onClick={() => void link(ref)}>Connect</button></div>)}
    <p className="vn-hint">Connection verifies the provider identity and enables refresh for this link only.</p>
  </details>;
}
