import { useState } from 'react';
import { Check, ChevronRight, Plus } from 'lucide-react';
import { callBackend, CrmRecord } from '../../api';
import { Selection } from '../../domain/vnext';
import { date, localDayEnd, LoadState, PageHeading, Pager, Refresh, Segments, useWorkspaceView } from './WorkspacePrimitives';

export function TasksWorkspace({ query, select, create }: { query: string; select: (selection: Selection) => void; create: () => void }) {
  const [bucket, setBucket] = useState('today');
  const [status, setStatus] = useState('open');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const result = useWorkspaceView('tasks', query, { bucket, status, day_end: localDayEnd() });
  const groups = new Map<string, CrmRecord[]>();
  for (const task of result.data?.items || []) {
    const metadata = task.metadata as Record<string, unknown> | undefined;
    const group = String(metadata?.category || task.priority || 'normal');
    groups.set(group, [...(groups.get(group) || []), task]);
  }
  async function complete(task: CrmRecord) {
    setBusy(true); setError('');
    try { await callBackend({ action: 'crm.update_task', id: task.id, status: status === 'done' ? 'open' : 'done' }); result.refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to update task.'); }
    finally { setBusy(false); }
  }
  return <section className="product-page">
    <PageHeading eyebrow="YOUR NEXT STEPS" title="Tasks" description="Daily commitments, relationship follow-ups and the next commercial step."><Refresh run={result.refresh} /><button onClick={create}><Plus size={16} />New task</button></PageHeading>
    <div className="product-filterbar"><Segments label="Task horizon" value={bucket} change={setBucket} choices={[[ 'today', 'Today' ], [ 'week', '1–7 days' ], [ 'month', '8–30 days' ], [ 'unscheduled', 'No date' ], [ 'all', 'All dates' ]]} /><select aria-label="Task status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="open">Open</option><option value="done">Completed</option></select></div>
    <div className="product-summary-strip"><strong>{result.data?.total || 0} tasks in this view</strong><span>{result.data?.summary.open || 0} open overall</span><span>Today includes overdue tasks · your local timezone</span></div>
    <LoadState loading={result.loading} error={result.error || error} empty={!result.data?.items.length}>No tasks in this period. Choose another range or add your next step.</LoadState>
    {!result.loading && [...groups].map(([group, tasks]) => <details className="product-task-group product-card" key={group} open><summary><span>{group}</span><small>{tasks.length}</small></summary>{tasks.map((task, index) => <article className="product-task-card" key={task.id}><span className="product-task-number">{index + 1}</span><div><button className="product-task-title" onClick={() => select({ entity: 'task', record: task })}>{task.title}<ChevronRight size={16} /></button><p>{task.body || 'Open the task to add context, relationships and connected work.'}</p><div className="product-task-meta"><span className="product-badge">{String(task.priority || 'normal')}</span><span>{date(task.due_at)}</span>{task.contact_id || task.account_id || task.deal_id ? <span>Linked CRM context</span> : null}</div></div><button className="product-complete" disabled={busy} aria-label={`${status === 'done' ? 'Reopen' : 'Complete'} ${task.title}`} onClick={() => void complete(task)}><Check size={17} /></button></article>)}</details>)}
    <Pager offset={result.offset} hasMore={!!result.data?.has_more} loading={result.loading} onChange={result.setOffset} />
  </section>;
}
