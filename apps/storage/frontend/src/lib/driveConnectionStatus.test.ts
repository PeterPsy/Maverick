import { expect, it } from 'vitest';
import { driveConnectionStatus } from './driveConnectionStatus';

it('allows Core-managed Drive accounts without app-owned credential references', () => {
  expect(driveConnectionStatus({
    id: 'platform_google_a', status: 'connected',
    external_refs: { managed_by: 'platform', platform_account_id: 'google_a' },
  })).toBe('connected');
});

it('keeps withdrawn platform authority unavailable even with old local credentials', () => {
  expect(driveConnectionStatus({
    id: 'platform_google_a', status: 'disconnected',
    external_refs: { managed_by: 'platform', platform_account_id: 'google_a' },
    credential: { secret_ref: 'test-reference', status: 'active' },
  })).toBe('disconnected');
});

it('does not use legacy credentials for an invalid managed account projection', () => {
  expect(driveConnectionStatus({
    id: 'platform_google_b', status: 'connected',
    external_refs: { managed_by: 'platform', platform_account_id: 'google_a' },
    credential: { secret_ref: 'test-reference', status: 'active' },
  })).toBe('reconnect_required');
});

it('continues checking local credential metadata for manual Drive connections', () => {
  expect(driveConnectionStatus({ id: 'manual', status: 'connected' })).toBe('reconnect_required');
  expect(driveConnectionStatus({ id: 'manual', status: 'connected', credential: { secret_ref: 'test-reference', status: 'active' } })).toBe('connected');
  expect(driveConnectionStatus({ id: 'manual', status: 'error', credential: { secret_ref: 'test-reference', status: 'active' } })).toBe('error');
});
