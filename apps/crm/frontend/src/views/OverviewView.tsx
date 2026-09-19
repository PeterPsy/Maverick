import { useState } from 'react';
import { ArrowRight, Check, FileText } from 'lucide-react';
import { callBackend, CrmRecord } from '../api';
import { Selection, useLiveCrm } from '../domain/vnext';
import { titleFor } from '../domain/routing';
import { ViewId } from '../domain/types';
import { currency, date, LoadState, PageHeading, Refresh, Segments } from './workspace/WorkspacePrimitives';

type Overview = {
  overdue_tasks: number; pending_approvals: number; active_deal_count: number;
  tasks: CrmRecord[]; threads: CrmRecord[]; briefs: CrmRecord[]; recent_contacts: CrmRecord[]; recent_deals: CrmRecord[]; pipeline_stages: { id: string; name: string }[];
  pipeline: Array<{ currency: string; value: number; margin_minor: number }>;
  stage_totals: Array<{ stage_id: string; stage: string; currency: string; value: number; margin_minor: number; deal_count: number }>;
};

export function OverviewView({ select, navigate, createTask }: { select: (selection: Selection) => void; navigate: (view: ViewId) => void; createTask: () => void }) {
  const result = useLiveCrm<Overview>({ action: 'crm.overview' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState('');
  const [briefId, setBriefId] = useState('');
  const [unit, setUnit] = useState('');
  const [metric, setMetric] = useState('value');
  const data = result.data;
  const brief = data?.briefs.find((item) => item.id === briefId) || data?.briefs[0];
  const currencies = [...new Set([...(data?.pipeline || []), ...(data?.stage_totals || [])].map((row) => row.currency))];
  const activeCurrency = currencies.includes(unit) ? unit : currencies[0] || 'EUR';
  const totals = data?.pipeline.find((row) => row.currency === activeCurrency);
  const observedStages = data?.stage_totals.filter((row) => row.currency === activeCurrency) || [];
  const stages = [...(data?.pipeline_stages || []).map((stage) => observedStages.find((row) => row.stage_id === stage.id) || { stage_id: stage.id, stage: stage.name, currency: activeCurrency, value: 0, margin_minor: 0, deal_count: 0 }), ...observedStages.filter((row) => !data?.pipeline_stages?.some((stage) => stage.id === row.stage_id))];
  const stageValue = (row: typeof stages[number]) => metric === 'value' ? row.value : row.margin_minor / 100;
  const max = Math.max(1, ...stages.map((row) => Math.abs(stageValue(row))));
  async function complete(task: CrmRecord) {
    setSaving(task.id); setError('');
    try { await callBackend({ action: 'crm.update_task', id: task.id, status: 'done' }); result.refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to complete task.'); }
    finally { setSaving(''); }
  }
  return <section className="product-page product-dashboard">
    <PageHeading eyebrow="CRM OVERVIEW" title="Dashboard" description={`Your relationships, decisions and next steps · ${date(new Date().toISOString())}`}><Refresh run={result.refresh} /></PageHeading>
    <LoadState loading={result.loading && !data} error={result.error || error} empty={false} />
    {data ? <>
      <section className="product-card product-weekly-brief"><header><div className="product-card-title"><FileText size={19} /><h2>Weekly brief</h2></div><div className="vn-actions">{data.briefs.length ? <select aria-label="Select brief" value={brief?.id} onChange={(event) => setBriefId(event.target.value)}>{data.briefs.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select> : null}<button onClick={() => navigate('briefs')}>Archive <ArrowRight size={14} /></button></div></header>
        {brief ? <><small>{date(brief.period_start)} – {date(brief.period_end)}</small><h3>{brief.title}</h3><p className="product-brief-body">{brief.body || 'No summary added.'}</p><button onClick={() => select({ entity: 'brief', record: brief })}>Read brief & linked context <ArrowRight size={14} /></button></> : <div className="product-empty"><h3>Your next brief starts here</h3><p>Capture priorities, meeting outcomes and risks. No generated or sample business data.</p><button onClick={() => navigate('briefs')}>Create a brief</button></div>}
      </section>
      <div className="product-currency"><span>Financial view · currencies are never combined</span>{currencies.length ? <select aria-label="Dashboard currency" value={activeCurrency} onChange={(event) => setUnit(event.target.value)}>{currencies.map((code) => <option key={code}>{code}</option>)}</select> : null}</div>
      <div className="product-metrics">
        <button onClick={() => navigate('deals')}><small>OPEN PIPELINE</small><strong>{currency(totals?.value, activeCurrency)}</strong><span>Unclosed opportunities</span></button>
        <button onClick={() => navigate('deals')}><small>ACTIVE DEALS</small><strong>{data.active_deal_count}</strong><span>All currencies</span></button>
        <button onClick={() => navigate('today')}><small>PRIORITY TASKS</small><strong>{data.overdue_tasks}</strong><span>Overdue commitments</span></button>
        <button onClick={() => navigate('reports')}><small>EXPECTED MARGIN</small><strong>{currency((totals?.margin_minor || 0) / 100, activeCurrency)}</strong><span>Open pipeline · not weighted</span></button>
      </div>
      <div className="product-dashboard-grid"><section className="product-card"><header><h2>Pipeline by stage</h2><Segments label="Pipeline metric" value={metric} change={setMetric} choices={[[ 'value', 'Value' ], [ 'margin', 'Margin' ]]} /></header>
        {stages.length ? stages.map((row) => <button className="product-stage" key={row.stage_id} onClick={() => navigate('deals')}><span>{row.stage}<small>{row.deal_count} deals</small></span><span className="product-stage-track"><i style={{ width: `${Math.abs(stageValue(row)) / max * 100}%` }} /></span><strong>{currency(stageValue(row), activeCurrency)}</strong></button>) : <div className="product-empty">Your deals will appear here, grouped by stage.</div>}
      </section><section className="product-card"><header><h2>Next tasks</h2><button onClick={createTask}>New task</button></header>{data.tasks.length ? data.tasks.slice(0, 3).map((task) => <div className="product-task-preview" key={task.id}><button className="product-complete" disabled={!!saving} aria-label={`Complete ${task.title}`} onClick={() => void complete(task)}><Check size={15} /></button><button className="product-row" onClick={() => select({ entity: 'task', record: task })}><strong>{task.title}</strong><small>{date(task.due_at)} · {String(task.priority || 'normal')}</small></button></div>) : <div className="product-empty">Nothing waiting on you</div>}<button className="product-card-link" onClick={() => navigate('today')}>All tasks <ArrowRight size={14} /></button></section>
      <section className="product-card"><header><h2>Latest people</h2><button onClick={() => navigate('people')}>View all</button></header>{(data.recent_contacts || []).length ? data.recent_contacts.map((record) => <button className="product-person-row" key={record.id} onClick={() => select({ entity: 'contact', record })}><span className="product-avatar" aria-hidden="true">{titleFor(record).slice(0, 2).toUpperCase()}</span><span><strong>{titleFor(record)}</strong><small>{record.email || 'No email added'}</small></span><ArrowRight size={14} /></button>) : <div className="product-empty">Your relationships will appear here.</div>}</section>
      <section className="product-card"><header><h2>Latest threads</h2><button onClick={() => navigate('conversations')}>View all</button></header>{data.threads.length ? data.threads.slice(0, 4).map((record) => <button className="product-row" key={record.id} onClick={() => select({ entity: 'conversation_thread', record })}><strong>{record.title}</strong><span>{record.body || 'Open conversation context'}</span><small>{String(record.channel || 'conversation')} · {record.status}</small></button>) : <div className="product-empty">Connect a conversation to people and a next step.</div>}</section>
      <section className="product-card product-deals-preview"><header><h2>Projects in progress</h2><button onClick={() => navigate('deals')}>All deals</button></header>{data.recent_deals?.length ? data.recent_deals.map((record) => <button className="product-row" key={record.id} onClick={() => select({ entity: 'deal', record })}><strong>{titleFor(record)}</strong><small>{record.stage} · {currency(record.value, record.currency)} · Close {date(record.close_date)}</small></button>) : <div className="product-empty">Create a deal to track potential revenue and its relationships.</div>}</section></div>
    </> : null}
  </section>;
}
