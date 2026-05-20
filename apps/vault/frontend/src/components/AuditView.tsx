import { Clock3 } from 'lucide-react';
import { AuditRecord } from '../api';
import { EmptyState, Status } from './VaultShared';

export function AuditView({ audit }: { audit: AuditRecord[] }) {
  return (
    <section className="vault-timeline">
      <div className="vault-panel-header">
        <div>
          <h2><Clock3 size={17} />Audit Trail</h2>
          <p>Core audit metadata only. Secret values are never returned to this app.</p>
        </div>
        <span>{audit.length} events</span>
      </div>
      {audit.length ? audit.map((item) => (
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
