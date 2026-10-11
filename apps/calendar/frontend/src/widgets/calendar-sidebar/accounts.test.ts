import { expect, it } from 'vitest';
import { buildAccountGroups } from './accounts';

it('keeps OAuth attempts out of the account tree and shows the account once completed', () => {
  const attempt = { id: 'attempt', provider: 'google', account_label: 'Google Calendar', status: 'pending' };
  const existing = { id: 'work', provider: 'google', account_id: 'ana@example.com', status: 'connected' };
  const remoteCalendar = { id: 'primary', connection_id: 'work', provider: 'google', provider_calendar_id: 'primary' };
  const connections = [attempt, existing];

  const groups = buildAccountGroups([], connections, [remoteCalendar]);
  expect(groups.map((group) => group.id)).toEqual(['calendar', 'work']);
  expect(groups[1].calendars).toEqual([remoteCalendar]);
  expect(connections).toEqual([attempt, existing]);

  const completed = { ...attempt, account_label: 'other@example.com', status: 'connected' };
  expect(buildAccountGroups([], [completed, existing], []).map((group) => group.id)).toEqual(['calendar', 'work', 'attempt']);
});


it('distinguishes mailboxes with the same display name using email first', () => {
  const groups = buildAccountGroups([], [
    { id: 'second', provider: 'google', account_id: 'b@example.com', account_label: 'Same Name', status: 'connected' },
    { id: 'first', provider: 'google', account_id: 'a@example.com', account_label: 'Same Name', status: 'connected' },
  ], []);
  expect(groups.slice(1).map(({ id, name, displayName }) => ({ id, name, displayName }))).toEqual([
    { id: 'first', name: 'a@example.com', displayName: 'Same Name' },
    { id: 'second', name: 'b@example.com', displayName: 'Same Name' },
  ]);
});
