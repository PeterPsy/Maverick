import { useState } from 'react';
import { ArrowLeft, Pencil } from 'lucide-react';
import { callBackend, CrmRecord } from '../api';
import { ExtensionSchema, label, Selection, useLiveCrm } from '../domain/vnext';
import { ExtensionComposer } from './ExtensionComposer';
import { ExtensionRecords } from './ExtensionList';
import { RecordRelationships } from './RecordRelationships';

export function ExtensionDetail({ selected, select, onClose }: { selected: Selection; select: (selection: Selection) => void; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [childType, setChildType] = useState('campaign_variant');
  const [error, setError] = useState('');
  const schema = useLiveCrm<ExtensionSchema>({ action: 'crm.extension_schema' });
  const current = useLiveCrm<{ record: CrmRecord; external_refs: Array<{ id: string; title: string; source_app_id: string; source_entity_id: string }> }>({ action: 'crm.record_context', entity_type: selected.entity, id: selected.record.id });
  const record = current.data?.record || selected.record;
  async function archive() {
    if (!window.confirm('Archive this record? Its data will be retained.')) return;
    try { await callBackend({ action: 'crm.archive_record', entity_type: selected.entity, id: record.id }); onClose(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to archive record.'); }
  }
  return <section className="vn-page vn-extension-detail"><header className="vn-page-heading"><div><button onClick={onClose}><ArrowLeft size={16} />Back</button><small>{label(selected.entity)}</small><h1>{record.title}</h1></div><div className="vn-actions"><button onClick={() => setEditing(true)}><Pencil size={15} />Edit</button><button onClick={() => void archive()}>Archive</button></div></header>
    {error || current.error ? <p className="crm-alert" role="alert">{error || current.error}</p> : null}
    <div className="vn-overview-grid"><section className="vn-surface"><h2>Record context</h2><p className="vn-prose">{record.body || 'No notes yet.'}</p><dl className="vn-fields">{Object.keys(schema.data?.entities[selected.entity]?.fields || {}).map((key) => <div key={key}><dt>{label(key)}</dt><dd>{typeof record[key] === 'object' ? <pre>{JSON.stringify(record[key], null, 2)}</pre> : String(record[key] ?? '—')}</dd></div>)}</dl>
      {record.metadata && typeof record.metadata === 'object' && Object.keys(record.metadata).length ? <details><summary>Import provenance</summary><pre className="vn-provenance">{JSON.stringify(record.metadata, null, 2)}</pre></details> : null}
    </section><div><RecordRelationships selected={{ ...selected, record }} select={select} /><section className="vn-surface"><h2>Linked app records</h2>{current.data?.external_refs.length ? current.data.external_refs.map((ref) => <p key={ref.id} className="vn-hint">{ref.title} · {ref.source_app_id}<br /><code>{ref.source_entity_id}</code></p>) : <p className="vn-hint">Link Mail, Calendar, files, transcripts or checklists through the selected providers.</p>}<button onClick={current.refresh}>Refresh links</button></section></div></div>
    {selected.entity === 'campaign' ? <section className="vn-surface"><nav className="vn-tabs" aria-label="Campaign workspace">{['campaign_variant', 'campaign_step', 'campaign_member', 'campaign_event'].map((type) => <button key={type} className={childType === type ? 'is-active' : ''} onClick={() => setChildType(type)}>{label(type.replace('campaign_', ''))}s</button>)}</nav><ExtensionRecords key={childType} entity={childType} campaignId={record.id} select={select} /><p className="vn-hint">Events are a business log, not delivery receipts. Campaign planning never sends messages.</p></section> : null}
    {editing ? <ExtensionComposer entity={selected.entity} record={record} onClose={() => setEditing(false)} onSaved={(updated) => { setEditing(false); select({ entity: selected.entity, record: updated }); current.refresh(); }} /> : null}
  </section>;
}
