import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CircleUserRound, LogOut, RefreshCw, Square, SquareCheck } from 'lucide-react';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  MAIL_INTERACTIVE_SYNC_THREADS,
  type MailConnection,
} from '../../api';
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

const MAILBOXES = ['inbox', 'sent', 'drafts', 'starred', 'trash'];
const MAIL_DATA_RESOURCES = new Set(['connections', 'drafts', 'threads', 'view-state']);
const GMAIL_OAUTH_SECRETS = ['gmail-oauth-client-id', 'gmail-oauth-client-secret'];
const GMAIL_REFRESH_SECRET = 'gmail-refresh-token';

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

function mailboxFromContext(context: WidgetContext) {
  const mailbox = context.content?.payload?.active_app_params?.mailbox;
  return typeof mailbox === 'string' && MAILBOXES.includes(mailbox) ? mailbox : null;
}

function connectionIdFromContext(context: WidgetContext) {
  const connectionId = context.content?.payload?.active_app_params?.connection_id;
  return typeof connectionId === 'string' && connectionId.trim() ? connectionId : null;
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
  const [mailbox, setMailbox] = useState('inbox');
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [activeOperation, setActiveOperation] = useState('');
  const [isMobileLayout, setIsMobileLayout] = useState(false);

  const refresh = useCallback(async (options: { preserveNotice?: boolean } = {}) => {
    try {
      const [connectionPayload, countPayload] = await Promise.all([
        callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() }),
        callBackend<MailboxCountPayload>({ action: MAIL_BACKEND_ACTIONS.mailboxesCounts, ...noSecretRequest() })
      ]);
      setConnections(connectionPayload.items);
      setMailboxCounts(countPayload.counts || {});
      if (!options.preserveNotice) {
        setNotice('');
      }
      return true;
    } catch (error) {
      if (!options.preserveNotice) {
        setNotice(error instanceof Error ? error.message : 'Unable to load mail.');
      }
      return false;
    }
  }, []);

  useEffect(() => {
    loadWidgetContext().then((context) => {
      const nextMailbox = mailboxFromContext(context);
      if (nextMailbox) {
        setMailbox(nextMailbox);
      }
      const nextConnectionId = connectionIdFromContext(context);
      setSelectedConnectionId(nextConnectionId);
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
        const nextMailbox = mailboxFromContext(payload.context);
        if (nextMailbox) {
          setMailbox(nextMailbox);
        }
        const nextConnectionId = connectionIdFromContext(payload.context);
        setSelectedConnectionId(nextConnectionId);
        setIsMobileLayout(isMobileFromContext(payload.context));
        return;
      }
      if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'mail') {
        const nextMailbox = payload.selection?.mailbox;
        if (typeof nextMailbox === 'string' && MAILBOXES.includes(nextMailbox)) {
          setMailbox(nextMailbox);
        }
        const nextConnectionId = payload.selection?.connection_id;
        if (typeof nextConnectionId === 'string' && nextConnectionId.trim()) {
          setSelectedConnectionId(nextConnectionId);
        }
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
  }, [refresh]);

  const activeConnections = useMemo(() => connections.filter((item) => item.status !== 'disconnected'), [connections]);
  const connection = (selectedConnectionId ? connections.find((item) => item.id === selectedConnectionId) : null) || activeConnections[0] || connections[0];
  const accountTreeNodes = useMemo(
    () => buildMailTree(connections, mailboxCounts, connection?.id || '', mailbox),
    [connections, mailboxCounts, connection?.id, mailbox],
  );
  const defaultExpandedIds = useMemo(
    () => accountTreeNodes.flatMap((node) => collectDefaultExpandedIds(node)),
    [accountTreeNodes],
  );
  const selectedNodeIds = useMemo(
    () => connection?.id ? [mailboxIdentity(connection.id, mailbox)] : [],
    [connection?.id, mailbox],
  );
  const treeProviderKey = `${connections.length}:${Object.keys(mailboxCounts).length}:${defaultExpandedIds.join('|')}`;

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
        ...gmailSecretRequest(targetConnection.id)
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

  function selectMailbox(nextMailbox: string, nextConnectionId: string | null = selectedConnectionId) {
    setMailbox(nextMailbox);
    if (nextConnectionId) {
      setSelectedConnectionId(nextConnectionId);
    }
    openMail({ mailbox: nextMailbox, connection_id: nextConnectionId });
    if (isMobileLayout) {
      closeShellSidebar();
    }
  }

  function countLabel(count: number) {
    return count === 1 ? '1 thread' : `${count} threads`;
  }

  function selectTreeNode(node: MailTreeNode) {
    if (node.type === 'mailbox' && node.mailbox && node.account) {
      selectMailbox(node.mailbox, node.account.id);
    }
  }

  return (
    <main className={`mail-sidebar-widget ${isMobileLayout ? 'is-shell-mobile' : ''}`} aria-busy={Boolean(activeOperation)}>
      <div className="mail-sidebar-widget__list mail-sidebar-widget__tree-list">
        {connections.length ? (
          <TreeProvider
            animateExpand
            className="mail-folder-tree"
            defaultExpandedIds={defaultExpandedIds}
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
    ? <CircleUserRound className="h-4 w-4" />
    : isMailboxActive
      ? <SquareCheck className="mail-folder-tree-filter-icon is-active h-4 w-4" />
      : <Square className="mail-folder-tree-filter-icon h-4 w-4" />;

  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        className={isDisconnected ? 'mail-folder-tree-muted' : ''}
        onClick={() => {
          onSelect(node);
        }}
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

function buildMailTree(
  connections: MailConnection[],
  mailboxCounts: Record<string, Record<string, MailboxCount>>,
  selectedConnectionId: string,
  selectedMailbox: string,
): MailTreeNode[] {
  return connections
    .slice()
    .sort((left, right) => accountName(left).localeCompare(accountName(right)))
    .map((account) => ({
      account,
      children: MAILBOXES.map((folder) => {
        const count = mailboxCounts[account.id]?.[folder] || { total: 0, unread: 0 };
        return {
          account,
          children: [],
          count,
          id: mailboxIdentity(account.id, folder),
          label: folder,
          mailbox: folder,
          status: account.id === selectedConnectionId && folder === selectedMailbox ? 'active' : 'mailbox',
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
}

function collectDefaultExpandedIds(node: MailTreeNode) {
  const ids: string[] = [];

  function visit(current: MailTreeNode) {
    if (current.children.length) {
      ids.push(current.id);
    }
    current.children.forEach(visit);
  }

  visit(node);
  return ids;
}

function accountIdentity(connectionId: string) {
  return `mail-account:${connectionId}`;
}

function mailboxIdentity(connectionId: string, folder: string) {
  return `mailbox:${connectionId}:${folder}`;
}

function accountName(connection: MailConnection) {
  return connection.display_name || connection.email_address || connection.id || 'Gmail';
}

createRoot(document.getElementById('mail-sidebar-root') as HTMLElement).render(<MailSidebarWidget />);
