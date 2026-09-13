import type { MailConnection } from './api';
import {
  aggregateMailboxScopeId, connectionMailboxScopeId, normalizeMailboxScopeIds,
  parseMailboxScopeId, type Mailbox,
} from './mailboxScopes';

export function toggleAggregateMailboxScope(currentScopeIds: string[], mailbox: Mailbox, connections: MailConnection[]) {
  const selected = isAggregateMailboxSelected(currentScopeIds, mailbox, connections);
  const withoutMailbox = scopeIdsExceptMailbox(currentScopeIds, mailbox);
  return selected ? withoutMailbox : [...withoutMailbox, aggregateMailboxScopeId(mailbox)];
}

export function toggleConnectionMailboxScope(
  currentScopeIds: string[],
  connectionId: string,
  mailbox: Mailbox,
  connections: MailConnection[],
) {
  const aggregateScopeId = aggregateMailboxScopeId(mailbox);
  const connectionScopeId = connectionMailboxScopeId(connectionId, mailbox);
  const selected = isConnectionMailboxSelected(currentScopeIds, connectionId, mailbox);
  const normalizedScopeIds = normalizeMailboxScopeIds(currentScopeIds);
  if (selected) {
    const nextScopeIds = normalizedScopeIds.filter((scopeId) => scopeId !== aggregateScopeId && scopeId !== connectionScopeId);
    if (normalizedScopeIds.includes(aggregateScopeId)) {
      const siblingScopeIds = connections
        .filter((connection) => connection.id !== connectionId)
        .map((connection) => connectionMailboxScopeId(connection.id, mailbox));
      return compactMailboxScopeIds([...nextScopeIds, ...siblingScopeIds], connections);
    }
    return compactMailboxScopeIds(nextScopeIds, connections);
  }
  return compactMailboxScopeIds(
    [...normalizedScopeIds.filter((scopeId) => scopeId !== aggregateScopeId), connectionScopeId],
    connections,
  );
}

function scopeIdsExceptMailbox(scopeIds: string[], mailbox: Mailbox) {
  return normalizeMailboxScopeIds(scopeIds).filter((scopeId) => parseMailboxScopeId(scopeId)?.mailbox !== mailbox);
}

export function compactMailboxScopeIds(scopeIds: string[], connections: MailConnection[]) {
  const normalizedScopeIds = normalizeMailboxScopeIds(scopeIds);
  const normalizedSet = new Set(normalizedScopeIds);
  const compacted: string[] = [];
  for (const scopeId of normalizedScopeIds) {
    const scope = parseMailboxScopeId(scopeId);
    if (!scope) {
      continue;
    }
    if (scope.connectionId && normalizedSet.has(aggregateMailboxScopeId(scope.mailbox))) {
      continue;
    }
    if (
      scope.connectionId &&
      connections.length > 0 &&
      connections.every((connection) => normalizedSet.has(connectionMailboxScopeId(connection.id, scope.mailbox)))
    ) {
      const aggregateScopeId = aggregateMailboxScopeId(scope.mailbox);
      if (!compacted.includes(aggregateScopeId)) {
        compacted.push(aggregateScopeId);
      }
      continue;
    }
    if (!compacted.includes(scopeId)) {
      compacted.push(scopeId);
    }
  }
  return compacted;
}

export function isAggregateMailboxSelected(scopeIds: string[], mailbox: Mailbox, connections: MailConnection[]) {
  const normalizedSet = new Set(normalizeMailboxScopeIds(scopeIds));
  if (normalizedSet.has(aggregateMailboxScopeId(mailbox))) {
    return true;
  }
  return connections.length > 0 && connections.every((connection) => normalizedSet.has(connectionMailboxScopeId(connection.id, mailbox)));
}

export function isConnectionMailboxSelected(scopeIds: string[], connectionId: string, mailbox: Mailbox) {
  const normalizedSet = new Set(normalizeMailboxScopeIds(scopeIds));
  return normalizedSet.has(aggregateMailboxScopeId(mailbox)) || normalizedSet.has(connectionMailboxScopeId(connectionId, mailbox));
}

export function mailboxScopeIdsForConnections(scopeIds: string[], connections: MailConnection[]) {
  const connectionIds = new Set(connections.map((connection) => connection.id));
  const filtered = normalizeMailboxScopeIds(scopeIds).filter((scopeId) => {
    const scope = parseMailboxScopeId(scopeId);
    return Boolean(scope && (!scope.connectionId || connectionIds.has(scope.connectionId)));
  });
  return filtered;
}
