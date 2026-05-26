import { SecretGrant } from '../api';
import { grantResourceScopeLabel, grantStatus } from '../vaultUtils';
import { DataPanel, EmptyState, Status } from './VaultShared';

export function GrantsView({ grants }: {
  grants: SecretGrant[];
}) {
  return (
    <DataPanel title="Grants" count={grants.length}>
      {grants.length ? (
        <table>
          <thead>
            <tr><th>Grant</th><th>Scope</th><th>Actions</th><th>Targets</th><th>Expiry</th><th>Status</th></tr>
          </thead>
          <tbody>
            {grants.map((grant) => (
              <tr key={grant.grant_id}>
                <td><strong>{grant.app_id}</strong><span>{grant.logical_name}</span></td>
                <td><span>{grantResourceScopeLabel(grant)}</span></td>
                <td>{grant.actions.join(', ')}</td>
                <td>{grant.target_patterns.join(', ')}</td>
                <td>{grant.expires_at ? new Date(grant.expires_at).toLocaleString() : 'never'}</td>
                <td><Status value={grantStatus(grant)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <EmptyState title="No grants match this view" />}
    </DataPanel>
  );
}
