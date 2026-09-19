import { useState } from 'react';
import { ArrowRight, Plus, RefreshCw } from 'lucide-react';
import { CrmRecord } from '../api';
import { extensionPages, label, Selection, useLiveCrm } from '../domain/vnext';
import { ExtensionComposer } from './ExtensionComposer';

export function ExtensionList({ page, query, select }: { page: string; query: string; select: (selection: Selection) => void }) {
  const config = extensionPages[page];
  const [entity, setEntity] = useState(config.entities[0]);
  return <section className="vn-page">
    <header className="vn-page-heading"><div><small>WORKSPACE CRM</small><h1>{config.title}</h1><p>{config.description}</p></div></header>
    {config.entities.length > 1 ? <nav className="vn-tabs" aria-label={`${config.title} categories`}>{config.entities.map((type) => <button key={type} className={entity === type ? 'is-active' : ''} onClick={() => setEntity(type)}>{label(type)}</button>)}</nav> : null}
    <ExtensionRecords key={`${entity}:${query}`} entity={entity} query={query} select={select} />
  </section>;
}

export function ExtensionRecords({ entity, query = '', campaignId, select }: { entity: string; query?: string; campaignId?: string; select: (selection: Selection) => void }) {
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const result = useLiveCrm<{ records: CrmRecord[]; has_more: boolean }>({ action: 'crm.list_extension_records', entity_type: entity, query, offset, limit: 24, ...(campaignId ? { campaign_id: campaignId } : {}) });
  return <>
    <div className="vn-list-toolbar"><h2>{label(entity)}s</h2><div><button aria-label="Refresh records" onClick={result.refresh}><RefreshCw size={16} /></button><button className="vn-primary" onClick={() => setCreating(true)}><Plus size={16} />New {label(entity).toLowerCase()}</button></div></div>
    {result.error ? <p className="crm-alert" role="alert">{result.error}</p> : null}
    {result.loading ? <p className="vn-hint">Loading records…</p> : null}
    <div className="vn-card-grid">{result.data?.records.map((record) => <button className="vn-record-card" key={record.id} onClick={() => select({ entity, record })}>
      <span className="vn-card-kicker">{String(record.status || record.category || record.channel || label(entity))}<ArrowRight size={16} /></span>
      <h3>{record.title}</h3><p>{record.body || record.objective || record.website ? String(record.body || record.objective || record.website) : 'Open to add context and related records.'}</p>
      <span className="vn-card-footer">{entity === 'expense' ? `${record.currency || 'EUR'} ${(Number(record.amount_minor || 0) / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : String(record.updated_at || '').slice(0, 10)}</span>
    </button>)}</div>
    {!result.loading && !result.error && !result.data?.records.length ? <div className="vn-empty"><h3>No {label(entity).toLowerCase()}s yet</h3><p>Create your first record or import your existing data. No demo data is added.</p></div> : null}
    <div className="vn-pagination"><button disabled={!offset || result.loading} onClick={() => setOffset((value) => Math.max(0, value - 24))}>Previous</button><span>Page {offset / 24 + 1}</span><button disabled={!result.data?.has_more || result.loading} onClick={() => setOffset((value) => value + 24)}>Next</button></div>
    {creating ? <ExtensionComposer entity={entity} defaults={campaignId ? { campaign_id: campaignId } : {}} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); result.refresh(); }} /> : null}
  </>;
}
