import { ArrowRight, Check, Clock3, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { callBackend, CrmRecord } from '../api';
import { Selection, useLiveCrm } from '../domain/vnext';
import { titleFor } from '../domain/routing';
import { ViewId } from '../domain/types';

type Overview = {
  counts: Record<string, number>; overdue_tasks: number; pending_approvals: number;
  tasks: CrmRecord[]; threads: CrmRecord[]; briefs: CrmRecord[]; activities: CrmRecord[];
  pipeline: Array<{ currency: string; value: number; weighted_value: number; margin_minor: number }>;
  expenses: Array<{ currency: string; amount_minor: number }>;
};

export function OverviewView({ select, navigate, today = false, createTask }: { select: (selection: Selection) => void; navigate: (view: ViewId) => void; today?: boolean; createTask: () => void }) {
  const result = useLiveCrm<Overview>({ action: 'crm.overview' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState('');
  const data = result.data;
  async function complete(task: CrmRecord) {
    setSaving(task.id); setError('');
    try { await callBackend({ action: 'crm.update_task', id: task.id, status: 'done' }); result.refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to complete task.'); }
    finally { setSaving(''); }
  }
  return <section className="vn-page">
    <header className="vn-page-heading"><div><small>{new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</small><h1>{today ? 'Your next steps' : 'The relationship workspace'}</h1><p>A clear view of your people, commitments and opportunities.</p></div><button onClick={result.refresh} aria-label="Refresh overview"><RefreshCw size={18} /></button></header>
    {result.error || error ? <p className="crm-alert" role="alert">{result.error || error}</p> : null}
    {result.loading && !data ? <p>Loading overview…</p> : null}
    {data ? <>
      <div className="vn-metrics">
        <button onClick={() => navigate('records')}><small>RELATIONSHIPS</small><strong>{(data.counts.contacts || 0) + (data.counts.accounts || 0)}</strong><span>People & companies <ArrowRight size={14} /></span></button>
        <button onClick={() => navigate('today')}><small>NEEDS ATTENTION</small><strong>{data.overdue_tasks}</strong><span>Overdue follow-ups <Clock3 size={14} /></span></button>
        <button onClick={() => navigate('pipeline')}><small>YOUR DECISION</small><strong>{data.pending_approvals}</strong><span>Pending approvals <ArrowRight size={14} /></span></button>
        <button onClick={() => navigate('campaigns')}><small>CAMPAIGN PLANNING</small><strong>{data.counts.campaigns || 0}</strong><span>No automatic deliveries <ArrowRight size={14} /></span></button>
      </div>
      <div className="vn-overview-grid"><section className="vn-surface">
        <div className="vn-list-toolbar"><h2>Follow-ups & commitments</h2><button onClick={createTask}>New task</button></div>
        {!data.tasks.length ? <div className="vn-empty"><Check size={26} /><h3>Nothing waiting on you</h3><p>Add a next step to keep your relationships moving.</p></div> : data.tasks.map((task) => <div className="vn-task" key={task.id}>
          <button className="vn-check" disabled={!!saving} aria-label={`Complete ${task.title}`} onClick={() => void complete(task)}><Check size={15} /></button>
          <button className="vn-task-title" onClick={() => select({ entity: 'task', record: task })}><strong>{task.title}</strong><span>{String(task.due_at || 'No due date').replace('T', ' ').slice(0, 16)} · {String(task.priority || 'normal')}</span></button>
        </div>)}
      </section><section className="vn-surface"><h2>Sales at a glance</h2>
        {data.pipeline.length ? data.pipeline.map((currency) => <div className="vn-financial" key={currency.currency}><small>{currency.currency} · OPEN PIPELINE</small><strong>{Number(currency.value).toLocaleString()}</strong><p>Weighted {Number(currency.weighted_value).toLocaleString()} · Margin {(currency.margin_minor / 100).toLocaleString()}</p></div>) : <p className="vn-hint">Your open deals will appear here.</p>}
        {data.expenses.map((currency) => <p className="vn-hint" key={currency.currency}>Expenses · {currency.currency} {(currency.amount_minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>)}
        <button onClick={() => navigate('pipeline')}>Open sales pipeline <ArrowRight size={15} /></button>
      </section></div>
      {!today ? <div className="vn-overview-grid"><section className="vn-surface"><div className="vn-list-toolbar"><h2>Recent conversations</h2><button onClick={() => navigate('conversations')}>View all</button></div>{data.threads.length ? data.threads.map((record) => <button className="vn-row" key={record.id} onClick={() => select({ entity: 'conversation_thread', record })}><strong>{record.title}</strong><span>{record.body || 'Open conversation context'}</span></button>) : <p className="vn-hint">Connect threads to people and your next actions.</p>}</section>
      <section className="vn-surface"><div className="vn-list-toolbar"><h2>Briefs & meeting notes</h2><button onClick={() => navigate('intelligence')}>View all</button></div>{data.briefs.length ? data.briefs.map((record) => <button className="vn-row" key={record.id} onClick={() => select({ entity: 'brief', record })}><strong>{titleFor(record)}</strong><span>{record.body || 'Open brief'}</span></button>) : <p className="vn-hint">Capture meeting outcomes and periodic priorities here.</p>}</section></div> : null}
    </> : null}
  </section>;
}
