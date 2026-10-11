import { expect, it } from 'vitest';
import { accountEmail, accountDisplayName, accountLabel } from './accountLabels';

it('keeps equally named accounts distinguishable in senders and actions', () => {
  const a = { id: 'a', email_address: 'first@example.com', display_name: 'Same Name', provider: 'gmail', status: 'connected' };
  const b = { id: 'b', email_address: 'second@example.com', display_name: 'Same Name', provider: 'gmail', status: 'connected' };
  expect(accountEmail(a)).toBe('first@example.com');
  expect(accountLabel(a)).toBe('first@example.com (Same Name)');
  expect(accountLabel(b)).toBe('second@example.com (Same Name)');
  expect(accountDisplayName({ ...a, display_name: a.email_address })).toBe('');
  expect(accountLabel({ id: 'legacy', display_name: 'Legacy account', email_address: '', provider: 'imap_smtp', status: 'connected' })).toBe('Legacy account');
});
