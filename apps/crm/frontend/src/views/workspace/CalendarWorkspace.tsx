import { FormEvent, useState } from 'react';
import { CalendarDays, Plus } from 'lucide-react';
import { callBackend, CrmRecord } from '../../api';
import { providerHref, LinkedRef } from '../../domain/integrations';
import { Selection } from '../../domain/vnext';
import { RecordPicker } from '../ExtensionComposer';
import { date, LoadState, PageHeading, Pager, Refresh, Segments, useWorkspaceView } from './WorkspacePrimitives';

export function CalendarWorkspace({ query, select }: { query: string; select: (selection: Selection) => void }) {
  const [range, setRange] = useState('week');
  const [day, setDay] = useState(() => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; });
  const [creating, setCreating] = useState(false);
  const [entity, setEntity] = useState('contact');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const start = new Date(`${day}T00:00:00`), end = new Date(start);
  end.setDate(end.getDate() + (range === 'day' ? 1 : range === 'week' ? 7 : 30));
  const result = useWorkspaceView('calendar', query, range === 'all' || !day ? {} : { from: start.toISOString(), until: end.toISOString() });
  const groups = new Map<string, CrmRecord[]>();
  for (const item of result.data?.items || []) {
    const meta = item.metadata as Record<string, unknown> || {};
    const key = date(meta.startTime || item.occurred_at);
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  async function open(entityType: string, id: string) {
    setBusy(true); setError('');
    try { const response = await callBackend<{ record: CrmRecord }>({ action: 'crm.get_record', entity_type: entityType, id }); select({ entity: entityType, record: response.record }); setCreating(false); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to open context.'); }
    finally { setBusy(false); }
  }
  function choose(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void open(entity, String(new FormData(event.currentTarget).get('record_id'))); }
  return <section className="product-page"><PageHeading eyebrow="MEETINGS & CONTEXT" title="Calendar" description="Linked Calendar events, meeting briefs and outcomes. The provider remains the source of truth."><Refresh run={result.refresh} /><button onClick={() => setCreating(!creating)}><Plus size={16} />New meeting</button></PageHeading>
    <div className="product-filterbar"><Segments label="Calendar range" value={range} change={setRange} choices={[[ 'day', 'Day' ], [ 'week', '7 days' ], [ 'month', '30 days' ], [ 'all', 'All linked events' ]]} /><input type="date" aria-label="Calendar starts on" value={day} onChange={(event) => { if (event.target.value) setDay(event.target.value); }} /></div>
    <p className="product-hint">CRM-linked snapshots only, not your entire calendar. Each row preserves its CRM relationship. Open the context to refresh, prepare a brief or record meeting outcomes.</p>
    {creating ? <form className="product-card vn-form" onSubmit={choose}><h2>Choose the meeting relationship</h2><label>CRM record type<select value={entity} onChange={(event) => setEntity(event.target.value)}>{['contact', 'account', 'deal', 'conversation_thread'].map((type) => <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>)}</select></label><label>Record<RecordPicker key={entity} entity={entity} name="record_id" required /></label><p>In Connected work, choose “Schedule meeting”, then review, approve and execute the proposal. No invitations are sent implicitly.</p><button disabled={busy}>Open scheduling context</button></form> : null}
    <LoadState loading={result.loading} error={result.error || error} empty={!result.data?.items.length}>No linked meetings in this range. Choose All linked events or connect a Calendar event from a CRM record.</LoadState>
    {!result.loading && [...groups].map(([dayLabel, items]) => <section className="product-agenda-day" key={dayLabel}><h2>{dayLabel}</h2>{items.map((item) => { const meta = item.metadata as Record<string, unknown> || {}; return <article className="product-card product-agenda-event" key={item.id}><CalendarDays size={22} /><div><h3>{item.title || 'Calendar event'}</h3><p>{item.summary}</p><small>{String(meta.startTime || item.occurred_at || 'No start time')} · {String(meta.location || 'No location')}</small><small>Last verified: {String(meta.last_synced_at || 'Not yet verified')} · {String(meta.resolution_status || 'Snapshot')}</small>{meta.last_error ? <p role="alert" className="crm-alert">{String(meta.last_error)} · Last good snapshot retained.</p> : null}<div className="vn-actions"><button disabled={busy} onClick={() => void open(String(item.crm_entity_type), String(item.crm_entity_id))}>Meeting context · {String(item.crm_entity_type)}</button><a href={providerHref(item as unknown as LinkedRef)} target="_top">Open in Calendar</a></div></div></article>; })}</section>)}
    <Pager offset={result.offset} hasMore={!!result.data?.has_more} loading={result.loading} onChange={result.setOffset} />
  </section>;
}
