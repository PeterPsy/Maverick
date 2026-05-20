import { useState } from 'react';
import { RotateCcw, ShieldCheck, Trash2 } from 'lucide-react';
import { SecretGrant, SecretRecord } from '../api';
import { grantStatus, grantUsesSecret, humanizeKind } from '../vaultUtils';
import { DataPanel, EmptyState, Status } from './VaultShared';

export function SecretsView(props: {
  secrets: SecretRecord[];
  grants: SecretGrant[];
  busy?: boolean;
  onRotate?: (secretId: string, value: string) => void;
  onDisable?: (secretId: string) => void;
  onRevoke?: (secretId: string) => void;
}) {
  const canMutate = Boolean(props.onRotate && props.onDisable && props.onRevoke);
  return (
    <DataPanel title="Secrets" count={props.secrets.length}>
      {props.secrets.length ? (
        <table>
          <thead>
            <tr><th>Secret</th><th>Kind</th><th>Status</th><th>Grants</th>{canMutate ? <th>Actions</th> : null}</tr>
          </thead>
          <tbody>
            {props.secrets.map((secret) => (
              <SecretRow canMutate={canMutate} key={secret.secret_id} secret={secret} {...props} />
            ))}
          </tbody>
        </table>
      ) : <EmptyState title="No secrets match this view" />}
    </DataPanel>
  );
}

function SecretRow({ secret, grants, busy = false, canMutate, onRotate, onDisable, onRevoke }: {
  secret: SecretRecord;
  grants: SecretGrant[];
  busy?: boolean;
  canMutate: boolean;
  onRotate?: (secretId: string, value: string) => void;
  onDisable?: (secretId: string) => void;
  onRevoke?: (secretId: string) => void;
}) {
  const [rotating, setRotating] = useState(false);
  const linkedGrants = grants.filter((grant) => grantUsesSecret(grant, secret) && grantStatus(grant) === 'active').length;
  return (
    <tr>
      <td><strong>{secret.label}</strong><span>{secret.alias || secret.secret_id}</span></td>
      <td>{humanizeKind(secret.kind)}</td>
      <td><Status value={secret.status} /></td>
      <td>{linkedGrants}</td>
      {canMutate && onRotate && onDisable && onRevoke ? <td className="vault-actions">
        {rotating ? (
          <form onSubmit={(event) => {
            event.preventDefault();
            const value = String(new FormData(event.currentTarget).get('raw_value') || '');
            onRotate(secret.secret_id, value);
            event.currentTarget.reset();
            setRotating(false);
          }}>
            <input name="raw_value" type="password" placeholder="New value" required />
            <button disabled={busy} title="Confirm rotation" type="submit"><RotateCcw size={15} /></button>
          </form>
        ) : (
          <button disabled={busy || secret.status === 'revoked'} onClick={() => setRotating(true)} title="Rotate" type="button"><RotateCcw size={15} /></button>
        )}
        <button disabled={busy || secret.status !== 'active'} onClick={() => onDisable(secret.secret_id)} title="Disable" type="button"><ShieldCheck size={15} /></button>
        <button disabled={busy || secret.status === 'revoked'} onClick={() => onRevoke(secret.secret_id)} title="Revoke" type="button"><Trash2 size={15} /></button>
      </td> : null}
    </tr>
  );
}
