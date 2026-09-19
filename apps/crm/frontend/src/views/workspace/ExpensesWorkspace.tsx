import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Selection } from '../../domain/vnext';
import { ExtensionComposer } from '../ExtensionComposer';
import { currency, date, LoadState, PageHeading, Pager, Refresh, useWorkspaceView } from './WorkspacePrimitives';

export function ExpensesWorkspace({ query, select }: { query: string; select: (selection: Selection) => void }) {
  const result = useWorkspaceView('expenses', query);
  const [creating, setCreating] = useState(false);
  const totals = result.data?.summary.currencies as { currency: string; amount_minor: number; total: number }[] || [];
  return <section className="product-page"><PageHeading eyebrow="ADMINISTRATION" title="Expenses" description="Business costs with their original currency, supplier and linked context."><Refresh run={result.refresh} /><button onClick={() => setCreating(true)}><Plus size={16} />New expense</button></PageHeading>
    <div className="product-metrics"><div><small>MOVEMENTS</small><strong>{result.data?.total || 0}</strong><span>Matching your search</span></div>{totals.map((total) => <div key={total.currency}><small>TOTAL · {total.currency}</small><strong>{currency(total.amount_minor / 100, total.currency)}</strong><span>{total.total} movements · not converted</span></div>)}</div>
    <LoadState loading={result.loading} error={result.error} empty={!result.data?.items.length} />
    {!result.loading ? <div className="product-table-scroll"><table className="product-table"><thead><tr><th>Date</th><th>Expense</th><th>Category</th><th>Supplier</th><th>Amount</th><th>Context / receipt</th></tr></thead><tbody>{result.data?.items.map((record) => <tr key={record.id}><td>{date(record.incurred_at)}</td><td><button onClick={() => select({ entity: 'expense', record })}>{record.title}</button></td><td>{String(record.category || '—')}</td><td>{String(record.supplier || '—')}</td><td><strong>{currency(Number(record.amount_minor) / 100, record.currency)}</strong></td><td><button onClick={() => select({ entity: 'expense', record })}>Open links</button></td></tr>)}</tbody></table></div> : null}
    <p className="product-hint">Receipts remain in Storage. Open an expense to link or preview its documents.</p>
    <Pager offset={result.offset} hasMore={!!result.data?.has_more} loading={result.loading} onChange={result.setOffset} />
    {creating ? <ExtensionComposer entity="expense" onClose={() => setCreating(false)} onSaved={() => { setCreating(false); result.refresh(); }} /> : null}
  </section>;
}
