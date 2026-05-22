import { AlertTriangle, ClipboardCheck, ExternalLink, ShieldAlert } from 'lucide-react';
import { ProviderStatus, SecretGrant, SecretGrantTarget, SecretRecord } from '../api';
import { computeReadinessIssues } from '../readiness';
import { EmptyState, Status } from './VaultShared';

export function ReadinessView({
  grants,
  onOpenGrants,
  providerStatus,
  secrets,
  targets
}: {
  grants: SecretGrant[];
  onOpenGrants: () => void;
  providerStatus: ProviderStatus | null;
  secrets: SecretRecord[];
  targets: SecretGrantTarget[];
}) {
  const issues = computeReadinessIssues({ grants, providerStatus, secrets, targets });
  const blocked = issues.filter((issue) => issue.severity === 'blocked').length;
  const warnings = issues.length - blocked;
  return (
    <section className="vault-readiness">
      <div className="vault-panel-header">
        <div>
          <h2><ClipboardCheck size={17} />Readiness</h2>
          <p>Configuration checks for declared app secrets, grants, linked secret state, and provider credentials.</p>
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
              <div>
                <strong>{issue.title}</strong>
                <p>{issue.detail}</p>
                <Status value={issue.status} />
              </div>
              {issue.action ? (
                <button onClick={onOpenGrants} type="button">
                  <ExternalLink size={15} />
                  <span>{issue.action}</span>
                </button>
              ) : null}
            </article>
          ))}
        </div>
      ) : <EmptyState title="All declared credential paths are ready" />}
    </section>
  );
}
