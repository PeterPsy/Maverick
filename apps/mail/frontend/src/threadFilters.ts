import type { MailThread } from './api';
import { normalizeMailboxScopeIds, parseMailboxScopeId } from './mailboxScopes';

/** Match the same union of account/folder scopes as threads.list. */
export function filterThreadsByMailboxScopes(threads: MailThread[], scopeIds: string[]) {
  const scopes = normalizeMailboxScopeIds(scopeIds).map((id) => parseMailboxScopeId(id)!);
  return threads.filter((thread) => scopes.some((scope) => (
    (!scope.connectionId || scope.connectionId === thread.connection_id)
    && thread.labels.includes(scope.mailbox)
  )));
}
