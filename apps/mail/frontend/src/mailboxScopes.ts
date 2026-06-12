export const MAILBOXES = ['inbox', 'sent', 'drafts', 'starred', 'trash'] as const;

export type Mailbox = (typeof MAILBOXES)[number];

export type MailboxScope = {
  connectionId: string | null;
  mailbox: Mailbox;
};

const AGGREGATE_SCOPE_PREFIX = 'all:';
const CONNECTION_SCOPE_PREFIX = 'connection:';

export const DEFAULT_MAILBOX_SCOPE_IDS = [aggregateMailboxScopeId('inbox')];

export function isMailbox(value: unknown): value is Mailbox {
  return typeof value === 'string' && MAILBOXES.includes(value as Mailbox);
}

export function aggregateMailboxScopeId(mailbox: Mailbox) {
  return `${AGGREGATE_SCOPE_PREFIX}${mailbox}`;
}

export function connectionMailboxScopeId(connectionId: string, mailbox: Mailbox) {
  return `${CONNECTION_SCOPE_PREFIX}${encodeURIComponent(connectionId)}:${mailbox}`;
}

export function parseMailboxScopeId(value: unknown): MailboxScope | null {
  const scopeId = typeof value === 'string' ? value.trim() : '';
  if (!scopeId) {
    return null;
  }
  if (scopeId.startsWith(AGGREGATE_SCOPE_PREFIX)) {
    const mailbox = scopeId.slice(AGGREGATE_SCOPE_PREFIX.length);
    return isMailbox(mailbox) ? { connectionId: null, mailbox } : null;
  }
  if (!scopeId.startsWith(CONNECTION_SCOPE_PREFIX)) {
    return null;
  }
  const withoutPrefix = scopeId.slice(CONNECTION_SCOPE_PREFIX.length);
  const mailboxSeparator = withoutPrefix.lastIndexOf(':');
  if (mailboxSeparator <= 0) {
    return null;
  }
  const encodedConnectionId = withoutPrefix.slice(0, mailboxSeparator);
  const mailbox = withoutPrefix.slice(mailboxSeparator + 1);
  if (!isMailbox(mailbox)) {
    return null;
  }
  try {
    const connectionId = decodeURIComponent(encodedConnectionId).trim();
    return connectionId ? { connectionId, mailbox } : null;
  } catch {
    return null;
  }
}

export function normalizeMailboxScopeIds(scopeIds: Iterable<unknown>) {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const scopeId of scopeIds) {
    const scope = parseMailboxScopeId(scopeId);
    if (!scope) {
      continue;
    }
    const normalizedId = scope.connectionId
      ? connectionMailboxScopeId(scope.connectionId, scope.mailbox)
      : aggregateMailboxScopeId(scope.mailbox);
    if (seen.has(normalizedId)) {
      continue;
    }
    seen.add(normalizedId);
    normalized.push(normalizedId);
  }
  return normalized;
}

export function parseMailboxScopeIds(value: unknown) {
  if (Array.isArray(value)) {
    return normalizeMailboxScopeIds(value);
  }
  if (typeof value !== 'string') {
    return [];
  }
  return normalizeMailboxScopeIds(value.split(','));
}

export function serializeMailboxScopeIds(scopeIds: Iterable<unknown>) {
  return normalizeMailboxScopeIds(scopeIds).join(',');
}

export function legacyMailboxScopeIds(mailboxValue: unknown, connectionIdValue: unknown) {
  if (!isMailbox(mailboxValue)) {
    return [];
  }
  const connectionId = typeof connectionIdValue === 'string' ? connectionIdValue.trim() : '';
  return [
    connectionId
      ? connectionMailboxScopeId(connectionId, mailboxValue)
      : aggregateMailboxScopeId(mailboxValue),
  ];
}

export function mailboxScopeIdsFromParams(
  params: Record<string, unknown> | undefined,
  fallback: string[] = DEFAULT_MAILBOX_SCOPE_IDS,
) {
  if (!params) {
    return fallback;
  }
  if (Object.prototype.hasOwnProperty.call(params, 'mailbox_scopes')) {
    return parseMailboxScopeIds(params.mailbox_scopes);
  }
  const legacyScopes = legacyMailboxScopeIds(params.mailbox, params.connection_id);
  return legacyScopes.length ? legacyScopes : fallback;
}

export function primaryMailboxScope(scopeIds: Iterable<unknown>): MailboxScope {
  const [scopeId] = normalizeMailboxScopeIds(scopeIds);
  const scope = parseMailboxScopeId(scopeId);
  return scope || { connectionId: null, mailbox: 'inbox' };
}
