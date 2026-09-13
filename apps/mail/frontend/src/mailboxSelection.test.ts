import { describe, expect, it } from 'vitest';
import type { MailConnection, MailThread } from './api';
import { MAILBOXES, connectionMailboxScopeId, mailboxScopeIdsFromParams, parseMailboxScopeId } from './mailboxScopes';
import {
  compactMailboxScopeIds, isAggregateMailboxSelected, isConnectionMailboxSelected,
  mailboxScopeIdsForConnections, toggleAggregateMailboxScope, toggleConnectionMailboxScope,
} from './mailboxSelection';
import { filterThreadsByMailboxScopes } from './threadFilters';

const accounts: MailConnection[] = ['a', 'b'].map((id) => ({
  id, provider: 'gmail', email_address: `${id}@example.com`, display_name: id, status: 'connected',
}));
const threads: MailThread[] = accounts.flatMap((account) => MAILBOXES.map((mailbox) => ({
  id: `${account.id}-${mailbox}`, connection_id: account.id, labels: [mailbox], subject: mailbox,
  snippet: '', participants: [], last_message_at: '', unread: true, starred: mailbox === 'starred',
})));
const ids = (scopes: string[]) => filterThreadsByMailboxScopes(threads, scopes).map((thread) => thread.id);

describe('Mail sidebar scopes', () => {
  it.each(MAILBOXES)('matches %s globally or for exactly one account', (mailbox) => {
    expect(ids([`all:${mailbox}`])).toEqual([`a-${mailbox}`, `b-${mailbox}`]);
    expect(ids([connectionMailboxScopeId('a', mailbox)])).toEqual([`a-${mailbox}`]);
  });

  it('unions folders and accounts, retaining input order and avoiding duplicate rows', () => {
    expect(ids(['all:inbox', 'connection:a:sent', 'connection:a:inbox', 'all:inbox']))
      .toEqual(['a-inbox', 'a-sent', 'b-inbox']);
    const overlap = { ...threads[0], labels: ['inbox', 'starred', 'sent'] };
    expect(filterThreadsByMailboxScopes([overlap], ['all:starred', 'all:sent'])).toEqual([overlap]);
    expect(filterThreadsByMailboxScopes([overlap], ['all:starred'])).toEqual([overlap]);
  });

  it('keeps an explicit empty selection empty after connection refresh', () => {
    expect(mailboxScopeIdsFromParams({ mailbox_scopes: '', mailbox: 'inbox' })).toEqual([]);
    expect(mailboxScopeIdsForConnections([], accounts)).toEqual([]);
    expect(mailboxScopeIdsForConnections(['connection:removed:inbox'], accounts)).toEqual([]);
    expect(ids([])).toEqual([]);
    expect(ids(['invalid', 'all:unknown', 'connection:%zz:sent'])).toEqual([]);
  });

  it('toggles aggregate folders independently and can turn the last checkbox off', () => {
    const selection = toggleAggregateMailboxScope(['all:inbox'], 'sent', accounts);
    expect(selection).toEqual(['all:inbox', 'all:sent']);
    expect(toggleAggregateMailboxScope(selection, 'inbox', accounts)).toEqual(['all:sent']);
    expect(toggleAggregateMailboxScope(['all:inbox'], 'inbox', accounts)).toEqual([]);
  });

  it('unchecking an account inside All keeps its siblings and other folders selected', () => {
    const selection = toggleConnectionMailboxScope(['all:inbox', 'all:sent'], 'a', 'inbox', accounts);
    expect(ids(selection)).toEqual(['a-sent', 'b-inbox', 'b-sent']);
    expect(isAggregateMailboxSelected(selection, 'inbox', accounts)).toBe(false);
    expect(isConnectionMailboxSelected(selection, 'a', 'inbox')).toBe(false);
    expect(isConnectionMailboxSelected(selection, 'b', 'inbox')).toBe(true);
    expect(toggleConnectionMailboxScope(selection, 'a', 'inbox', accounts)).toEqual(['all:sent', 'all:inbox']);
  });

  it('compacts complete per-account selections and respects partial aggregate toggles', () => {
    expect(compactMailboxScopeIds(['connection:a:sent', 'connection:b:sent'], accounts)).toEqual(['all:sent']);
    expect(toggleAggregateMailboxScope(['connection:a:sent', 'all:inbox'], 'sent', accounts))
      .toEqual(['all:inbox', 'all:sent']);
    expect(toggleAggregateMailboxScope(['connection:a:sent', 'connection:b:sent'], 'sent', accounts)).toEqual([]);
  });

  it('round-trips account identifiers with scope delimiters without leaking other accounts', () => {
    const connectionId = 'user:alias, café@example.com';
    const scopeId = connectionMailboxScopeId(connectionId, 'drafts');
    expect(parseMailboxScopeId(scopeId)).toEqual({ connectionId, mailbox: 'drafts' });
    const thread = { ...threads[0], connection_id: connectionId, labels: ['drafts'] };
    expect(filterThreadsByMailboxScopes([thread, ...threads], [scopeId])).toEqual([thread]);
  });
});
