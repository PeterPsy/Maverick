import { Trash2 } from 'lucide-react';
import { SecretGrant } from '../api';
import { grantStatus } from '../vaultUtils';
import { DataPanel, EmptyState, Status } from './VaultShared';

export function GrantsView({ grants, busy, onRevoke }: {
  grants: SecretGrant[];
  busy?: boolean;
  onRevoke?: (grantId: string) => void;
}) {
  return (
    <DataPanel title="Grants" count={grants.length}>
      {grants.length ? (
        <table>
          <thead>
            <tr><th>Grant</th><th>Actions</th><th>Targets</th><th>Expiry</th><th>Status</th>{onRevoke ? <th></th> : null}</tr>
          </thead>
          <tbody>
            {grants.map((grant) => (
              <tr key={grant.grant_id}>
                <td><strong>{grant.app_id}</strong><span>{grant.logical_name}</span></td>
                <td>{grant.actions.join(', ')}</td>
                <td>{grant.target_patterns.join(', ')}</td>
                <td>{grant.expires_at ? new Date(grant.expires_at).toLocaleString() : 'never'}</td>
                <td><Status value={grantStatus(grant)} /></td>
                {onRevoke ? <td><button disabled={busy || grantStatus(grant) !== 'active'} onClick={() => onRevoke(grant.grant_id)} title="Revoke" type="button"><Trash2 size={15} /></button></td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      ) : <EmptyState title="No grants match this view" />}
    </DataPanel>
  );
}
