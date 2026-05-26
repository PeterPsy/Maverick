import { SecretGrant, SecretRecord } from '../api';
import { ConnectionIssue } from '../readiness';
import { grantStatus, grantUsesSecret, humanizeKind } from '../vaultUtils';
import { DataPanel, EmptyState, Status } from './VaultShared';

export function SecretsView(props: {
  secrets: SecretRecord[];
  grants: SecretGrant[];
  issues?: ConnectionIssue[];
}) {
  return (
    <DataPanel caption="Redacted credential inventory and current app usage." title="Credential Inbox" count={props.secrets.length}>
      {props.secrets.length ? (
        <table>
          <thead>
            <tr><th>Credential</th><th>Kind</th><th>Status</th><th>Used by</th><th>Last updated</th><th>Health</th></tr>
          </thead>
          <tbody>
            {props.secrets.map((secret) => (
              <SecretRow key={secret.secret_id} secret={secret} {...props} />
            ))}
          </tbody>
        </table>
      ) : <EmptyState title="No secrets match this view" />}
    </DataPanel>
  );
}

function SecretRow({ secret, grants, issues = [] }: {
  secret: SecretRecord;
  grants: SecretGrant[];
  issues?: ConnectionIssue[];
}) {
  const linkedGrants = grants.filter((grant) => grantUsesSecret(grant, secret) && grantStatus(grant) === 'active');
  const usedBy = Array.from(new Set(linkedGrants.map((grant) => grant.app_id))).sort();
  const issueCount = issues.filter((issue) => issue.credentialSecretIds.includes(secret.secret_id)).length;
  return (
    <tr>
      <td><strong>{secret.label}</strong><span>{secret.alias || secret.secret_id}</span></td>
      <td>{humanizeKind(secret.kind)}</td>
      <td><Status value={secret.status} /></td>
      <td>{usedBy.length ? usedBy.join(', ') : 'Not in use'}</td>
      <td>{new Date(secret.updated_at).toLocaleString()}</td>
      <td>
        <Status value={issueCount ? 'needs-attention' : 'healthy'} />
        <span>{issueCount ? `${issueCount} issue${issueCount === 1 ? '' : 's'}` : 'No open issues'}</span>
      </td>
    </tr>
  );
}
