import { AlertTriangle, ClipboardCheck, ShieldAlert } from 'lucide-react';
import { ConnectionIssue } from '../readiness';
import { EmptyState, Status } from './VaultShared';

export function ConnectionIssuesView({ issues }: {
  issues: ConnectionIssue[];
}) {
  const blocked = issues.filter((issue) => issue.severity === 'blocked').length;
  const warnings = issues.length - blocked;
  return (
    <section className="vault-readiness">
      <div className="vault-panel-header">
        <div>
          <h2><ClipboardCheck size={17} />Connection Issues</h2>
          <p>Credential paths that need a saved value, a user decision, or an admin review.</p>
        </div>
        <span>{blocked} blocked · {warnings} review</span>
      </div>
      {issues.length ? (
        <div className="vault-readiness-list">
          {issues.map((issue) => (
            <article className={`vault-readiness-item is-${issue.severity}`} key={issue.id}>
              <span className="vault-readiness-item__icon" aria-hidden="true">
                {issue.severity === 'blocked' ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}
              </span>
              <div className="vault-readiness-item__body">
                <strong>{issue.title}</strong>
                <p>{issue.summary}</p>
                <dl>
                  <div><dt>App</dt><dd>{issue.appDisplayName}</dd></div>
                  <div><dt>Credential</dt><dd>{issue.credentialLabel}</dd></div>
                  <div><dt>Severity</dt><dd><Status value={issue.severity} /></dd></div>
                  <div><dt>User input</dt><dd>{issue.userInputNeeded ? 'Needed' : 'Not needed'}</dd></div>
                  <div><dt>Recommended action</dt><dd>{issue.recommendedAction}</dd></div>
                </dl>
                <details className="vault-technical-details">
                  <summary>Technical details</summary>
                  <p>{issue.technicalDetails}</p>
                </details>
              </div>
            </article>
          ))}
        </div>
      ) : <EmptyState title="All credential connections are ready" />}
    </section>
  );
}
