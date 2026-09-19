import { useState } from 'react';
import { ArrowRight, Building2, Plus, Users } from 'lucide-react';
import { callBackend, PipelineStage, RecordsTablePayload } from '../../api';
import { Selection, useLiveCrm } from '../../domain/vnext';
import { CreatableEntity, ViewId } from '../../domain/types';
import { currency, date, LoadState, PageHeading, Refresh } from './WorkspacePrimitives';

export function RelationshipsWorkspace({ entity, query, select, create, navigate, stages }: { entity: 'contact' | 'account' | 'deal'; query: string; select: (selection: Selection) => void; create: (entity: CreatableEntity) => void; navigate: (view: ViewId) => void; stages: PipelineStage[] }) {
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState('updated_at');
  const key = JSON.stringify({ entity, query, status, sort });
  const [page, setPage] = useState({ key, cursors: [''] });
  const cursors = page.key === key ? page.cursors : [''];
  const result = useLiveCrm<RecordsTablePayload>({ action: 'crm.records_table', entity_type: entity, query, filters: status ? { status } : {}, sort: { field: sort, direction: sort === 'name' ? 'asc' : 'desc' }, pagination: { limit: 40, cursor: cursors.at(-1) || '' } });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const title = entity === 'contact' ? 'People' : entity === 'account' ? 'Companies' : 'Deals';
  async function move(id: string, stageId: string) {
    setBusy(true); setError('');
    try { await callBackend({ action: 'crm.move_deal', id, stage_id: stageId }); result.refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to change stage.'); }
    finally { setBusy(false); }
  }
  return <section className="product-page">
    <PageHeading eyebrow={entity === 'deal' ? 'OPPORTUNITIES' : 'RELATIONSHIPS'} title={title} description={entity === 'contact' ? 'People, their companies and the next meaningful conversation.' : entity === 'account' ? 'Company context across people, opportunities and connected work.' : 'Commercial opportunities, value, margin and linked relationships.'}><Refresh run={result.refresh} /><button onClick={() => navigate(entity === 'deal' ? 'pipeline' : 'quality')}>{entity === 'deal' ? 'Kanban & operations' : 'Data quality'}</button><button onClick={() => create(entity)}><Plus size={16} />New {entity === 'contact' ? 'person' : entity === 'account' ? 'company' : 'deal'}</button></PageHeading>
    <div className="product-filterbar"><span>{result.data?.records.length || 0} records · page {cursors.length}</span><div className="vn-actions">{entity === 'deal' ? <select aria-label="Deal stage filter" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All stages</option>{stages.map((stage) => <option value={stage.id} key={stage.id}>{stage.name}</option>)}</select> : null}<select aria-label="Record order" value={sort} onChange={(event) => setSort(event.target.value)}><option value="updated_at">Recently updated</option><option value="name">Name A–Z</option></select><button onClick={() => navigate('records')}>Advanced filters</button></div></div>
    <LoadState loading={result.loading} error={result.error || error} empty={!result.data?.records.length} />
    {!result.loading && entity === 'account' ? <div className="product-company-grid">{result.data?.records.map((row) => <button className="product-company product-card" key={row.id} onClick={() => select({ entity, record: row.record })}><span className="product-company-icon"><Building2 size={22} /></span><h2>{row.title}</h2><p>{row.record.domain || 'No website added'}</p><div><span><Users size={15} />{String(row.computed?.contact_count ?? 0)} people</span><span>{String(row.computed?.open_task_count ?? 0)} open tasks</span></div><small>Open company context <ArrowRight size={13} /></small></button>)}</div> : !result.loading ? <div className="product-table-scroll"><table className="product-table"><thead><tr><th>{entity === 'deal' ? 'Deal' : 'Person'}</th><th>{entity === 'deal' ? 'Stage' : 'Company'}</th><th>{entity === 'deal' ? 'Value' : 'Email'}</th><th>{entity === 'deal' ? 'Margin' : 'Next action'}</th><th>{entity === 'deal' ? 'Close date' : 'Updated'}</th><th>Context</th></tr></thead><tbody>{result.data?.records.map((row) => <tr key={row.id}><td><button className="product-person-row" onClick={() => select({ entity, record: row.record })}><span className="product-avatar" aria-hidden="true">{row.title.slice(0, 2).toUpperCase()}</span><strong>{row.title}</strong></button></td><td>{entity === 'deal' ? <select aria-label={`Stage for ${row.title}`} value={row.record.stage_id || ''} disabled={busy} onChange={(event) => void move(row.record.id, event.target.value)}>{!stages.some((stage) => stage.id === row.record.stage_id) ? <option value={row.record.stage_id || ''}>{row.record.stage || 'Unassigned'}</option> : null}{stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.name}</option>)}</select> : row.display?.account || String(row.record.company || '—')}</td><td>{entity === 'deal' ? currency(row.record.value, row.record.currency) : row.record.email || '—'}</td><td>{entity === 'deal' ? currency(Number(row.record.margin_minor || 0) / 100, row.record.currency) : String(row.computed?.next_action || '—')}</td><td>{date(entity === 'deal' ? row.record.close_date : row.record.updated_at)}</td><td><button aria-label={`Open ${row.title}`} onClick={() => select({ entity, record: row.record })}><ArrowRight size={16} /></button></td></tr>)}</tbody></table></div> : null}
    <nav className="product-pager" aria-label="Relationship pagination"><button disabled={cursors.length === 1 || result.loading} onClick={() => setPage({ key, cursors: cursors.slice(0, -1) })}>Previous</button><span>Page {cursors.length}</span><button disabled={!result.data?.has_more || result.loading} onClick={() => setPage({ key, cursors: [...cursors, result.data?.next_cursor || ''] })}>Next</button></nav>
  </section>;
}
