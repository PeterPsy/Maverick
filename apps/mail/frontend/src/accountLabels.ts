import type { MailConnection } from './api';

export function accountEmail(connection?: MailConnection | null) {
  return connection?.email_address?.trim() || connection?.display_name?.trim() || connection?.id || 'Mail account';
}

export function accountDisplayName(connection?: MailConnection | null) {
  const name = connection?.display_name?.trim();
  return name && name !== accountEmail(connection) ? name : '';
}

export function accountLabel(connection?: MailConnection | null) {
  const name = accountDisplayName(connection);
  return accountEmail(connection) + (name ? ` (${name})` : '');
}
