import { ReactNode, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { CrmRecord } from '../../api';
import { useLiveCrm } from '../../domain/vnext';

export type WorkspaceResult = { items: CrmRecord[]; total: number; has_more: boolean; offset: number; summary: { open?: number; done?: number; reply?: number; waiting?: number; completed?: number; currencies?: { currency: string; amount_minor: number; total: number }[] } };
export function useWorkspaceView(view: string, query: string, filters: Record<string, unknown> = {}) {
  const key = JSON.stringify({ view, query, ...filters });
  const [page, setPage] = useState({ key, offset: 0 });
  const offset = page.key === key ? page.offset : 0;
  const result = useLiveCrm<WorkspaceResult>({ action: 'crm.workspace_view', view, query, ...filters, offset, limit: 40 });
  return { ...result, offset, setOffset: (next: number) => setPage({ key, offset: next }) };
}
export function PageHeading({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children?: ReactNode }) {
  return <header className="product-heading"><div><small>{eyebrow}</small><h1>{title}</h1><p>{description}</p></div><div className="vn-actions">{children}</div></header>;
}
export function LoadState({ loading, error, empty, children }: { loading: boolean; error: string; empty: boolean; children?: ReactNode }) {
  if (error) return <p role="alert" className="crm-alert">{error}</p>;
  if (loading) return <p role="status" className="product-empty">Loading workspace…</p>;
  if (empty) return <div className="product-empty">{children || 'No records in this view. Add a record or change your filters.'}</div>;
  return null;
}
export function Pager({ offset, hasMore, loading, onChange }: { offset: number; hasMore: boolean; loading: boolean; onChange: (offset: number) => void }) {
  return <nav className="product-pager" aria-label="Workspace pagination"><button disabled={!offset || loading} onClick={() => onChange(Math.max(0, offset - 40))}>Previous</button><span>Page {offset / 40 + 1}</span><button disabled={!hasMore || loading} onClick={() => onChange(offset + 40)}>Next</button></nav>;
}
export function Segments({ value, choices, change, label }: { value: string; choices: [string, string][]; change: (value: string) => void; label: string }) {
  return <div className="product-segments" role="group" aria-label={label}>{choices.map(([key, title]) => <button key={key} aria-pressed={value === key} onClick={() => change(key)}>{title}</button>)}</div>;
}
export function Refresh({ run }: { run: () => void }) { return <button onClick={run} aria-label="Refresh view"><RefreshCw size={16} /></button>; }
export function currency(value: unknown, code: unknown = 'EUR') {
  const amount = Number(value || 0), unit = String(code || 'EUR');
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: unit, maximumFractionDigits: 2 }).format(amount); }
  catch { return `${unit} ${amount.toLocaleString()}`; }
}
export function date(value: unknown) {
  if (!value) return 'No date';
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function localDayEnd() {
  const end = new Date(); end.setHours(23, 59, 59, 999);
  const minutes = -end.getTimezoneOffset();
  const suffix = `${minutes >= 0 ? '+' : '-'}${String(Math.floor(Math.abs(minutes) / 60)).padStart(2, '0')}:${String(Math.abs(minutes) % 60).padStart(2, '0')}`;
  return new Date(end.getTime() + minutes * 60000).toISOString().replace('Z', suffix);
}
