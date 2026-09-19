import { useState } from 'react';
import { ArrowRight, FileText, MessageSquare, Plus, Radar } from 'lucide-react';
import { Selection } from '../../domain/vnext';
import { ExtensionComposer } from '../ExtensionComposer';
import { date, LoadState, PageHeading, Pager, Refresh, Segments, useWorkspaceView } from './WorkspacePrimitives';

const specs = {
  conversations: { view: 'threads', entity: 'conversation_thread', title: 'Threads', eyebrow: 'CONVERSATIONS', description: 'What needs a reply, what is waiting and what has been resolved.', icon: MessageSquare },
  intelligence: { view: 'intelligence', entity: 'intelligence_profile', title: 'Intelligence', eyebrow: 'MARKET KNOWLEDGE', description: 'Competitive profiles, research and the context behind your decisions.', icon: Radar },
  briefs: { view: 'briefs', entity: 'brief', title: 'Brief archive', eyebrow: 'EXECUTIVE CONTEXT', description: 'Priorities, risks, stakeholders and meeting outcomes in one place.', icon: FileText },
};
export function ContextWorkspace({ page, query, select }: { page: keyof typeof specs; query: string; select: (selection: Selection) => void }) {
  const spec = specs[page];
  const [bucket, setBucket] = useState('reply');
  const [creating, setCreating] = useState(false);
  const result = useWorkspaceView(spec.view, query, page === 'conversations' ? { bucket } : {});
  const Icon = spec.icon;
  return <section className="product-page">
    <PageHeading eyebrow={spec.eyebrow} title={spec.title} description={spec.description}><Refresh run={result.refresh} /><button onClick={() => setCreating(true)}><Plus size={16} />New {spec.entity.replace(/_/g, ' ')}</button></PageHeading>
    {page === 'conversations' ? <div className="product-filterbar"><Segments label="Thread state" value={bucket} change={setBucket} choices={[[ 'reply', `To reply (${result.data?.summary.reply || 0})` ], [ 'waiting', `Waiting (${result.data?.summary.waiting || 0})` ], [ 'completed', `Completed (${result.data?.summary.completed || 0})` ]]} /><span>{result.data?.total || 0} threads</span></div> : null}
    <LoadState loading={result.loading} error={result.error} empty={!result.data?.items.length} />
    {!result.loading ? <div className={page === 'conversations' ? 'product-thread-list' : 'product-company-grid'}>{result.data?.items.map((record) => <button className={`product-card product-context-card ${page === 'conversations' ? 'is-thread' : ''}`} key={record.id} onClick={() => select({ entity: spec.entity, record })}><span className="product-company-icon"><Icon size={21} /></span><div><div className="product-context-title"><h2>{record.title}</h2><span className="product-badge">{String(record.status || record.category || 'Profile')}</span></div><p>{record.body || 'Add notes, evidence and linked records.'}</p><small>{page === 'conversations' ? `${record.channel || 'Conversation'} · ${date(record.last_activity_at || record.updated_at)}` : page === 'briefs' ? `${date(record.period_start)} – ${date(record.period_end)}` : `${record.website || 'No website'} · Reviewed ${date(record.reviewed_at)}`}</small></div><ArrowRight size={16} /></button>)}</div> : null}
    <Pager offset={result.offset} hasMore={!!result.data?.has_more} loading={result.loading} onChange={result.setOffset} />
    {creating ? <ExtensionComposer entity={spec.entity} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); result.refresh(); }} /> : null}
  </section>;
}
