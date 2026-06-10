import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LogOut, Mail, RefreshCw, Square, SquareCheck } from 'lucide-react';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  MAIL_INTERACTIVE_SYNC_THREADS,
  type MailConnection,
} from '../../api';
import {
  DEFAULT_MAILBOX_SCOPE_IDS,
  MAILBOXES,
  aggregateMailboxScopeId,
  connectionMailboxScopeId,
  mailboxScopeIdsFromParams,
  normalizeMailboxScopeIds,
  parseMailboxScopeId,
  primaryMailboxScope,
  serializeMailboxScopeIds,
  type Mailbox,
} from '../../mailboxScopes';
import {
  TreeExpander,
  TreeIcon,
  TreeLabel,
  TreeNode,
  TreeNodeContent,
  TreeNodeTrigger,
  TreeProvider,
  TreeView,
} from '../../components/ui/tree';
import './styles.css';

const MAILBOX_LABELS: Record<string, string> = {
  inbox: 'Inbox',
  sent: 'Sent',
  drafts: 'Drafts',
  starred: 'Starred',
  trash: 'Trash',
};
const MAIL_DATA_RESOURCES = new Set(['connections', 'drafts', 'threads', 'view-state']);
const GMAIL_OAUTH_SECRETS = ['gmail-oauth-client-id', 'gmail-oauth-client-secret'];
const GMAIL_REFRESH_SECRET = 'gmail-refresh-token';
const IMAP_SMTP_SECRET = 'mailbox-password';

type ConnectionPayload = {
  items: MailConnection[];
};

type MailboxCount = {
  total: number;
  unread: number;
};

type MailboxCountPayload = {
  counts: Record<string, Record<string, MailboxCount>>;
};

type WidgetContext = {
  content?: {
    payload?: {
      active_app_params?: Record<string, unknown>;
      is_mobile_layout?: boolean;
    };
  };
};

type MailTreeNode = {
  account?: MailConnection;
  children: MailTreeNode[];
  count?: MailboxCount;
  id: string;
  label: string;
  mailbox?: string;
  status?: string;
  title: string;
  type: 'account' | 'mailbox';
};

function noSecretRequest() {
  return { _app_secret_request: { logical_names: [], required: false } };
}

function gmailSecretRequest(connectionId?: string) {
  if (!connectionId) {
    return noSecretRequest();
  }
  return {
    _app_secret_request: {
      required: true,
      selectors: [
        { logical_names: GMAIL_OAUTH_SECRETS },
        {
          logical_names: [GMAIL_REFRESH_SECRET],
          resource_type: 'mail_connection',
          resource_id: connectionId
        }
      ]
    }
  };
}

function connectionSecretRequest(connection?: MailConnection | null) {
  if (!connection?.id) {
    return noSecretRequest();
  }
  if (connection.provider === 'imap_smtp') {
    return {
      _app_secret_request: {
        required: true,
        selectors: [
          {
            logical_names: [IMAP_SMTP_SECRET],
            resource_type: 'mail_connection',
            resource_id: connection.id
          }
        ]
      }
    };
  }
  return gmailSecretRequest(connection.id);
}

function contextToken() {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get('context') || new URLSearchParams(window.location.search).get('context') || '';
}

async function loadWidgetContext(): Promise<WidgetContext> {
  const token = contextToken();
  if (!token) {
    return {};
  }
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) {
    return {};
  }
  return (await response.json()).context as WidgetContext;
}

function mailboxScopeIdsFromContext(context: WidgetContext, fallback = DEFAULT_MAILBOX_SCOPE_IDS) {
  return mailboxScopeIdsFromParams(context.content?.payload?.active_app_params, fallback);
}

function isMobileFromContext(context: WidgetContext) {
  return context.content?.payload?.is_mobile_layout === true;
}

function openMail(params: Record<string, string | boolean | null>) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'mail',
      params
    },
    window.location.origin
  );
}

function closeShellSidebar() {
  window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
}

function MailSidebarWidget() {
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [mailboxCounts, setMailboxCounts] = useState<Record<string, Record<string, MailboxCount>>>({});
  const [mailboxScopeIds, setMailboxScopeIds] = useState<string[]>(DEFAULT_MAILBOX_SCOPE_IDS);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [activeOperation, setActiveOperation] = useState('');
  const [isMobileLayout, setIsMobileLayout] = useState(false);
  const refreshRequestRef = useRef(0);

  const refresh = useCallback(async (options: { preserveNotice?: boolean } = {}) => {
    const requestId = refreshRequestRef.current + 1;
    refreshRequestRef.current = requestId;
    setLoading(true);
    try {
      const [connectionPayload, countPayload] = await Promise.all([
        callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() }),
        callBackend<MailboxCountPayload>({ action: MAIL_BACKEND_ACTIONS.mailboxesCounts, ...noSecretRequest() })
      ]);
      if (refreshRequestRef.current !== requestId) {
        return false;
      }
      setConnections(connectionPayload.items);
      setMailboxCounts(countPayload.counts || {});
      if (!options.preserveNotice) {
        setNotice('');
      }
      return true;
    } catch (error) {
      if (refreshRequestRef.current !== requestId) {
        return false;
      }
      if (!options.preserveNotice) {
        setNotice(error instanceof Error ? error.message : 'Unable to load mail.');
      }
      return false;
    } finally {
      if (refreshRequestRef.current === requestId) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadWidgetContext().then((context) => {
      setMailboxScopeIds(mailboxScopeIdsFromContext(context));
      setIsMobileLayout(isMobileFromContext(context));
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        context?: WidgetContext;
        owner_app_id?: string;
        resource?: string;
        selection?: Record<string, unknown>;
        type?: string;
      };
      if (payload.type === 'maverick.widget.context-changed' && payload.context) {
        setMailboxScopeIds(mailboxScopeIdsFromContext(payload.context, mailboxScopeIds));
        setIsMobileLayout(isMobileFromContext(payload.context));
        return;
      }
      if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'mail') {
        setMailboxScopeIds(mailboxScopeIdsFromParams(payload.selection, mailboxScopeIds));
        return;
      }
      if (
        payload.type === 'maverick.widget.data-changed' &&
        payload.owner_app_id === 'mail' &&
        typeof payload.resource === 'string' &&
        MAIL_DATA_RESOURCES.has(payload.resource)
      ) {
        refresh();
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [mailboxScopeIds, refresh]);

  const accountTreeNodes = useMemo(
    () => buildMailTree(connections, mailboxCounts, mailboxScopeIds),
    [connections, mailboxCounts, mailboxScopeIds],
  );
  const selectedNodeIds = useMemo(
    () => selectedMailboxNodeIds(mailboxScopeIds, connections),
    [connections, mailboxScopeIds],
  );
  const treeProviderKey = useMemo(
    () => connections.map((connection) => connection.id).sort().join('|'),
    [connections],
  );

  async function sync(targetConnection: MailConnection) {
    if (targetConnection.status === 'disconnected') {
      setNotice('No connected mail provider is available to sync.');
      return;
    }
    setActiveOperation(`sync:${targetConnection.id}`);
    try {
      await callBackend({
        action: MAIL_BACKEND_ACTIONS.threadsSync,
        connection_id: targetConnection.id,
        max_threads: MAIL_INTERACTIVE_SYNC_THREADS,
        ...connectionSecretRequest(targetConnection)
      });
      const refreshed = await refresh({ preserveNotice: true });
      if (refreshed) {
        setNotice('Sync completed.');
      } else {
        setNotice('Sync completed. Refresh the view if the list is stale.');
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Sync failed.');
    } finally {
      setActiveOperation('');
    }
  }

  async function disconnect(targetConnection: MailConnection) {
    setActiveOperation(`disconnect:${targetConnection.id}`);
    try {
      const payload = await callBackend<{ disconnect?: { status?: string; detail?: string } }>({
        action: MAIL_BACKEND_ACTIONS.connectionsDisconnect,
        connection_id: targetConnection.id,
        reason: 'Disconnected from the Mail sidebar',
        ...noSecretRequest()
      });
      setNotice(payload.disconnect?.detail || `Connection ${payload.disconnect?.status || 'disconnected'}.`);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Disconnect failed.');
    } finally {
      setActiveOperation('');
    }
  }

  function applyMailboxScopeSelection(nextScopeIds: string[]) {
    const normalizedScopeIds = compactMailboxScopeIds(nextScopeIds, connections);
    const primaryScope = primaryMailboxScope(normalizedScopeIds);
    const nextSerializedMailboxScopes = serializeMailboxScopeIds(normalizedScopeIds);
    setMailboxScopeIds(normalizedScopeIds);
    openMail({
      mailbox: primaryScope.mailbox,
      mailbox_scopes: nextSerializedMailboxScopes,
      connection_id: primaryScope.connectionId,
    });
    if (isMobileLayout) {
      closeShellSidebar();
    }
  }

  function countLabel(count: number) {
    return count === 1 ? '1 thread' : `${count} threads`;
  }

  function selectTreeNode(node: MailTreeNode) {
    if (node.type === 'mailbox' && node.mailbox) {
      applyMailboxScopeSelection(toggleMailboxScope(mailboxScopeIds, node, connections));
    }
  }

  return (
    <main className={`mail-sidebar-widget ${isMobileLayout ? 'is-shell-mobile' : ''}`} aria-busy={loading || Boolean(activeOperation)}>
      <div className="mail-sidebar-widget__list mail-sidebar-widget__tree-list">
        {loading ? (
          <MailSidebarSkeleton />
        ) : connections.length ? (
          <TreeProvider
            animateExpand
            className="mail-folder-tree"
            indent={18}
            key={treeProviderKey}
            onSelectionChange={() => undefined}
            selectedIds={selectedNodeIds}
          >
            <TreeView>
              {accountTreeNodes.map((node, index) => (
                <MailTreeNodeView
                  activeOperation={activeOperation}
                  countLabel={countLabel}
                  isLast={index === accountTreeNodes.length - 1}
                  key={node.id}
                  level={0}
                  node={node}
                  onDisconnectConnection={disconnect}
                  onSelect={selectTreeNode}
                  onSyncConnection={sync}
                />
              ))}
            </TreeView>
          </TreeProvider>
        ) : (
          <p className="mail-sidebar-widget__empty">No mail accounts connected.</p>
        )}
        {notice ? <p className="mail-sidebar-widget__notice">{notice}</p> : null}
      </div>
    </main>
  );
}

function MailSidebarSkeleton() {
  return (
    <div className="mail-sidebar-skeleton" role="status" aria-label="Mail folders are loading">
      {Array.from({ length: 7 }).map((_, index) => (
        <div className={`mail-sidebar-skeleton__row depth-${Math.min(index, 3)}`} key={index} aria-hidden="true">
          <span className="mail-sidebar-skeleton__expander" />
          <span className="mail-sidebar-skeleton__icon" />
          <span className="mail-sidebar-skeleton__copy">
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

function MailTreeNodeView({ node, level, isLast, onSelect, onSyncConnection, onDisconnectConnection, activeOperation, countLabel }: {
  activeOperation: string;
  countLabel: (count: number) => string;
  isLast: boolean;
  level: number;
  node: MailTreeNode;
  onDisconnectConnection: (connection: MailConnection) => Promise<void>;
  onSelect: (node: MailTreeNode) => void;
  onSyncConnection: (connection: MailConnection) => Promise<void>;
}) {
  const hasChildren = node.children.length > 0;
  const isMailboxActive = node.type === 'mailbox' && node.status === 'active';
  const isDisconnected = node.account?.status === 'disconnected';
  const isSyncing = activeOperation === `sync:${node.account?.id}`;
  const isDisconnecting = activeOperation === `disconnect:${node.account?.id}`;
  const displayCount = node.mailbox === 'inbox' ? node.count?.unread || 0 : node.count?.total || 0;
  const label = node.type === 'account' && node.status && node.status !== 'connected' ? `${node.label} (${node.status})` : node.label;
  const icon = node.type === 'account'
    ? accountProviderIcon(node.account)
    : isMailboxActive
      ? <SquareCheck className="mail-folder-tree-filter-icon is-active h-4 w-4" />
      : <Square className="mail-folder-tree-filter-icon h-4 w-4" />;

  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        aria-checked={node.type === 'mailbox' ? isMailboxActive : undefined}
        className={isDisconnected ? 'mail-folder-tree-muted' : ''}
        onClick={() => {
          onSelect(node);
        }}
        role={node.type === 'mailbox' ? 'checkbox' : undefined}
      >
        <TreeExpander hasChildren={hasChildren} />
        <TreeIcon hasChildren={hasChildren} icon={icon} />
        <TreeLabel title={node.title}>{label}</TreeLabel>
        {node.type === 'mailbox' && displayCount > 0 ? <b className="mail-folder-tree-count">{displayCount}</b> : null}
        {node.type === 'mailbox' && displayCount === 0 ? (
          <span className="mail-folder-tree-meta">{node.mailbox === 'inbox' ? '0 unread' : countLabel(0)}</span>
        ) : null}
        {node.type === 'account' && node.account ? (
          <span className="mail-folder-tree-actions">
            <button
              aria-label={`Sync ${node.label}`}
              className="mail-folder-tree-sync"
              disabled={Boolean(activeOperation) || isDisconnected}
              onClick={(event) => {
                event.stopPropagation();
                void onSyncConnection(node.account!);
              }}
              type="button"
            >
              <RefreshCw className={isSyncing ? 'is-spinning' : ''} aria-hidden="true" />
            </button>
            <button
              aria-label={`Disconnect ${node.label}`}
              className="mail-folder-tree-sync mail-folder-tree-disconnect"
              disabled={Boolean(activeOperation) || isDisconnected}
              onClick={(event) => {
                event.stopPropagation();
                void onDisconnectConnection(node.account!);
              }}
              type="button"
            >
              <LogOut className={isDisconnecting ? 'is-spinning' : ''} aria-hidden="true" />
            </button>
          </span>
        ) : null}
      </TreeNodeTrigger>
      <TreeNodeContent hasChildren={hasChildren}>
        {node.children.map((child, index) => (
          <MailTreeNodeView
            activeOperation={activeOperation}
            countLabel={countLabel}
            isLast={index === node.children.length - 1}
            key={child.id}
            level={level + 1}
            node={child}
            onDisconnectConnection={onDisconnectConnection}
            onSelect={onSelect}
            onSyncConnection={onSyncConnection}
          />
        ))}
      </TreeNodeContent>
    </TreeNode>
  );
}

function accountProviderIcon(account?: MailConnection) {
  if (account?.provider === 'gmail') {
    return <GmailIcon className="mail-folder-tree-provider-icon h-4 w-4" />;
  }
  return <Mail className="mail-folder-tree-provider-icon h-4 w-4" />;
}

function GmailIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path fill="#F2F2F2" d="M5.2 5h13.6A2.2 2.2 0 0 1 21 7.2v9.6a2.2 2.2 0 0 1-2.2 2.2H5.2A2.2 2.2 0 0 1 3 16.8V7.2A2.2 2.2 0 0 1 5.2 5Z" />
      <path fill="#EA4335" d="M5.2 5h1.35L12 9.12 17.45 5h1.35A2.2 2.2 0 0 1 21 7.2v.62l-9 6.76-9-6.76V7.2A2.2 2.2 0 0 1 5.2 5Z" />
      <path fill="#34A853" d="M3 7.82 7.5 11.2V19H5.2A2.2 2.2 0 0 1 3 16.8Z" />
      <path fill="#FBBC04" d="M21 7.82V16.8a2.2 2.2 0 0 1-2.2 2.2h-2.3v-7.8Z" />
      <path fill="#4285F4" d="M7.5 19v-7.8L12 14.58l4.5-3.38V19Z" />
      <path fill="#C5221F" d="M3 7.82 12 14.58l9-6.76V10.4l-9 6.76-9-6.76Z" opacity="0.62" />
    </svg>
  );
}

function buildMailTree(
  connections: MailConnection[],
  mailboxCounts: Record<string, Record<string, MailboxCount>>,
  mailboxScopeIds: string[],
): MailTreeNode[] {
  const aggregateNodes = MAILBOXES.map((folder) => {
    const count = aggregateMailboxCount(mailboxCounts, folder);
    const selected = isAggregateMailboxSelected(mailboxScopeIds, folder, connections);
    return {
      children: [],
      count,
      id: aggregateMailboxIdentity(folder),
      label: `All ${MAILBOX_LABELS[folder].toLowerCase()}`,
      mailbox: folder,
      status: selected ? 'active' : 'mailbox',
      title: folder === 'inbox' ? `${count.unread} unread across all accounts` : `${count.total} threads across all accounts`,
      type: 'mailbox' as const,
    };
  });

  const accountNodes = connections
    .slice()
    .sort((left, right) => accountName(left).localeCompare(accountName(right)))
    .map((account) => ({
      account,
      children: MAILBOXES.map((folder) => {
        const count = mailboxCounts[account.id]?.[folder] || { total: 0, unread: 0 };
        const selected = isConnectionMailboxSelected(mailboxScopeIds, account.id, folder);
        return {
          account,
          children: [],
          count,
          id: mailboxIdentity(account.id, folder),
          label: MAILBOX_LABELS[folder] || folder,
          mailbox: folder,
          status: selected ? 'active' : 'mailbox',
          title: folder === 'inbox' ? `${count.unread} unread` : `${count.total} threads`,
          type: 'mailbox' as const,
        };
      }),
      id: accountIdentity(account.id),
      label: accountName(account),
      status: account.status || 'connected',
      title: account.email_address || account.provider || account.id,
      type: 'account' as const,
    }));

  return [...aggregateNodes, ...accountNodes];
}

function toggleMailboxScope(currentScopeIds: string[], node: MailTreeNode, connections: MailConnection[]) {
  if (!node.mailbox) {
    return currentScopeIds;
  }
  return node.account
    ? toggleConnectionMailboxScope(currentScopeIds, node.account.id, node.mailbox as Mailbox, connections)
    : toggleAggregateMailboxScope(currentScopeIds, node.mailbox as Mailbox, connections);
}

function toggleAggregateMailboxScope(currentScopeIds: string[], mailbox: Mailbox, connections: MailConnection[]) {
  const selected = isAggregateMailboxSelected(currentScopeIds, mailbox, connections);
  const withoutMailbox = scopeIdsExceptMailbox(currentScopeIds, mailbox);
  return selected ? withoutMailbox : [...withoutMailbox, aggregateMailboxScopeId(mailbox)];
}

function toggleConnectionMailboxScope(
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

function compactMailboxScopeIds(scopeIds: string[], connections: MailConnection[]) {
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

function isAggregateMailboxSelected(scopeIds: string[], mailbox: Mailbox, connections: MailConnection[]) {
  const normalizedSet = new Set(normalizeMailboxScopeIds(scopeIds));
  if (normalizedSet.has(aggregateMailboxScopeId(mailbox))) {
    return true;
  }
  return connections.length > 0 && connections.every((connection) => normalizedSet.has(connectionMailboxScopeId(connection.id, mailbox)));
}

function isConnectionMailboxSelected(scopeIds: string[], connectionId: string, mailbox: Mailbox) {
  const normalizedSet = new Set(normalizeMailboxScopeIds(scopeIds));
  return normalizedSet.has(aggregateMailboxScopeId(mailbox)) || normalizedSet.has(connectionMailboxScopeId(connectionId, mailbox));
}

function selectedMailboxNodeIds(scopeIds: string[], connections: MailConnection[]) {
  const selectedIds: string[] = [];
  for (const mailbox of MAILBOXES) {
    if (isAggregateMailboxSelected(scopeIds, mailbox, connections)) {
      selectedIds.push(aggregateMailboxIdentity(mailbox));
    }
    for (const connection of connections) {
      if (isConnectionMailboxSelected(scopeIds, connection.id, mailbox)) {
        selectedIds.push(mailboxIdentity(connection.id, mailbox));
      }
    }
  }
  return selectedIds;
}

function accountIdentity(connectionId: string) {
  return `mail-account:${connectionId}`;
}

function aggregateMailboxIdentity(folder: string) {
  return `mailbox:all:${folder}`;
}

function mailboxIdentity(connectionId: string, folder: string) {
  return `mailbox:${connectionId}:${folder}`;
}

function accountName(connection: MailConnection) {
  return connection.display_name || connection.email_address || connection.id || 'Gmail';
}

function aggregateMailboxCount(
  mailboxCounts: Record<string, Record<string, MailboxCount>>,
  folder: string,
): MailboxCount {
  return Object.values(mailboxCounts).reduce(
    (accumulator, counts) => {
      const count = counts[folder];
      if (!count) {
        return accumulator;
      }
      return {
        total: accumulator.total + count.total,
        unread: accumulator.unread + count.unread,
      };
    },
    { total: 0, unread: 0 },
  );
}

createRoot(document.getElementById('mail-sidebar-root') as HTMLElement).render(<MailSidebarWidget />);
