import type { DriveConnection } from '../types';

export function driveConnectionStatus(connection: Pick<DriveConnection, 'id' | 'status' | 'external_refs' | 'credential'>): DriveConnection['status'] | 'reconnect_required' {
  if (connection.status !== 'connected') return connection.status;
  if (connection.external_refs?.managed_by === 'platform') {
    const accountId = connection.external_refs.platform_account_id;
    return typeof accountId === 'string' && accountId && connection.id === `platform_${accountId}`
      ? 'connected' : 'reconnect_required';
  }
  return connection.credential?.secret_ref && connection.credential.status === 'active'
    ? 'connected' : 'reconnect_required';
}
