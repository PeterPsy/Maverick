import { useMemo, useState } from 'react';
import { Clock3, Download } from 'lucide-react';
import { AuditRecord } from '../api';
import { EmptyState, Status } from './VaultShared';

export function AuditView({ audit }: { audit: AuditRecord[] }) {
  const [appId, setAppId] = useState('');
  const [action, setAction] = useState('');
  const [status, setStatus] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const apps = useMemo(() => uniqueValues(audit.map((item) => item.app_id || '').filter(Boolean)), [audit]);
  const actions = useMemo(() => uniqueValues(audit.map((item) => item.action)), [audit]);
  const filtered = useMemo(() => audit.filter((item) => {
    if (appId && item.app_id !== appId) {
      return false;
    }
    if (action && item.action !== action) {
      return false;
    }
    if (status === 'review' && item.status !== 'failed' && item.status !== 'attempted') {
      return false;
    }
    if (status && status !== 'review' && item.status !== status) {
      return false;
    }
    const occurredAt = Date.parse(item.occurred_at);
    if (fromDate && occurredAt < Date.parse(fromDate)) {
      return false;
    }
    if (toDate && occurredAt > Date.parse(`${toDate}T23:59:59.999`)) {
      return false;
    }
    return true;
  }), [action, appId, audit, fromDate, status, toDate]);

  function exportAudit() {
    const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), items: filtered }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `vault-audit-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="vault-timeline">
      <div className="vault-panel-header">
        <div>
          <h2><Clock3 size={17} />Audit Trail</h2>
          <p>Core audit metadata only. Secret values are never returned to this app.</p>
        </div>
        <span>{filtered.length} events</span>
      </div>
      <div className="vault-audit-filters" aria-label="Audit filters">
        <select aria-label="Filter by app" onChange={(event) => setAppId(event.currentTarget.value)} value={appId}>
          <option value="">All apps</option>
          {apps.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select aria-label="Filter by action" onChange={(event) => setAction(event.currentTarget.value)} value={action}>
          <option value="">All actions</option>
          {actions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select aria-label="Filter by status" onChange={(event) => setStatus(event.currentTarget.value)} value={status}>
          <option value="">All statuses</option>
          <option value="review">Failed or attempted</option>
          <option value="failed">Failed</option>
          <option value="attempted">Attempted</option>
          <option value="succeeded">Succeeded</option>
        </select>
        <input aria-label="From date" onChange={(event) => setFromDate(event.currentTarget.value)} type="date" value={fromDate} />
        <input aria-label="To date" onChange={(event) => setToDate(event.currentTarget.value)} type="date" value={toDate} />
        <button disabled={!filtered.length} onClick={exportAudit} type="button"><Download size={15} /><span>Export</span></button>
      </div>
      {filtered.length ? filtered.map((item) => (
        <article key={item.audit_id}>
          <span><Status value={item.status} /></span>
          <div>
            <strong>{item.action}</strong>
            <p>{item.detail}</p>
            <time>{new Date(item.occurred_at).toLocaleString()}</time>
          </div>
        </article>
      )) : <EmptyState title="No audit events match this view" />}
    </section>
  );
}

function uniqueValues(values: string[]) {
  return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right));
}
