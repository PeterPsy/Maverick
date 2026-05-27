import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  type MailConnection,
} from '../../api';
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
  const [expandedConnectionIds, setExpandedConnectionIds] = useState<Set<string>>(() => new Set());
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [isMobileLayout, setIsMobileLayout] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [connectionPayload, countPayload] = await Promise.all([
        callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() }),
        callBackend<MailboxCountPayload>({ action: MAIL_BACKEND_ACTIONS.mailboxesCounts, ...noSecretRequest() })
      ]);
      setConnections(connectionPayload.items);
      setMailboxCounts(countPayload.counts || {});
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to load mail.');
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
      if (nextConnectionId) {
        expandConnection(nextConnectionId);
      }
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
        if (nextConnectionId) {
          expandConnection(nextConnectionId);
        }
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
          expandConnection(nextConnectionId);
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
  useEffect(() => {
    if (!connection?.id) {
      return;
    }
    setExpandedConnectionIds((current) => {
      if (current.size > 0) {
        return current;
      }
      return new Set([connection.id]);
    });
  }, [connection?.id]);

  async function sync(targetConnection: MailConnection) {
    if (targetConnection.status === 'disconnected') {
      setNotice('No connected mail provider is available to sync.');
      return;
    }
    setBusy(true);
    try {
      await callBackend({
        action: MAIL_BACKEND_ACTIONS.threadsSync,
        connection_id: targetConnection.id,
        ...gmailSecretRequest(targetConnection.id)
      });
      setNotice('Sync completed.');
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Sync failed.');
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(targetConnection: MailConnection) {
    setBusy(true);
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
      setBusy(false);
    }
  }

  function toggleConnection(nextConnectionId: string) {
    setExpandedConnectionIds((current) => {
      const next = new Set(current);
      if (next.has(nextConnectionId)) {
        next.delete(nextConnectionId);
      } else {
        next.add(nextConnectionId);
      }
      return next;
    });
  }

  function expandConnection(nextConnectionId: string) {
    setExpandedConnectionIds((current) => new Set(current).add(nextConnectionId));
  }

  function selectMailbox(nextMailbox: string, nextConnectionId: string | null = selectedConnectionId) {
    setMailbox(nextMailbox);
    if (nextConnectionId) {
      setSelectedConnectionId(nextConnectionId);
      expandConnection(nextConnectionId);
    }
    openMail({ mailbox: nextMailbox, connection_id: nextConnectionId });
    if (isMobileLayout) {
      closeShellSidebar();
    }
  }

  function countFor(connectionId: string, folder: string) {
    return mailboxCounts[connectionId]?.[folder] || { total: 0, unread: 0 };
  }

  function countLabel(count: number) {
    return count === 1 ? '1 thread' : `${count} threads`;
  }

  return (
    <main className={`mail-sidebar-widget ${isMobileLayout ? 'is-shell-mobile' : ''}`} aria-busy={busy}>
      <div className="mail-sidebar-widget__list">
        {connections.length ? connections.map((item) => {
          const selected = item.id === connection?.id;
          const expanded = expandedConnectionIds.has(item.id);
          const canSyncAccount = item.status !== 'disconnected';
          return (
            <section className="mail-sidebar-widget__account-group" aria-label={`${item.display_name || item.email_address} mailboxes`} key={item.id}>
              <button
                className={`mail-sidebar-widget__account-trigger mail-sidebar-widget__row ${selected ? 'is-selected' : ''}`}
                type="button"
                aria-expanded={expanded}
                onClick={() => toggleConnection(item.id)}
              >
                <span className={`mail-sidebar-widget__chevron ${expanded ? 'is-expanded' : ''}`} aria-hidden="true" />
                <span className="mail-sidebar-widget__row-copy">
                  <strong>{item.display_name || item.email_address}</strong>
                  <span>{item.email_address || item.provider}</span>
                </span>
                <small>{item.status}</small>
              </button>
              {expanded ? (
                <div className="mail-sidebar-widget__account-menu">
                  <nav className="mail-sidebar-widget__mailboxes" aria-label={`${item.display_name || item.email_address} folders`}>
                    {MAILBOXES.map((folder) => {
                      const activeMailbox = selected && folder === mailbox;
                      const folderCount = countFor(item.id, folder);
                      const displayCount = folder === 'inbox' ? folderCount.unread : folderCount.total;
                      return (
                        <button key={folder} className={activeMailbox ? 'active' : ''} onClick={() => selectMailbox(folder, item.id)} type="button">
                          <span className="mail-sidebar-widget__row-icon" aria-hidden="true">{folder.slice(0, 1).toUpperCase()}</span>
                          <span className="mail-sidebar-widget__row-copy">
                            <strong>{folder}</strong>
                            <span>{folder === 'inbox' ? `${folderCount.unread} unread` : countLabel(folderCount.total)}</span>
                          </span>
                          {displayCount > 0 ? <b>{displayCount}</b> : null}
                        </button>
                      );
                    })}
                  </nav>
                  <div className="mail-sidebar-widget__account-actions">
                    <button type="button" onClick={() => sync(item)} disabled={busy || !canSyncAccount}>
                      Sync
                    </button>
                    <button
                      type="button"
                      className="mail-sidebar-widget__danger-action"
                      onClick={() => disconnect(item)}
                      disabled={busy || !canSyncAccount}
                    >
                      Disconnect
                    </button>
                  </div>
                </div>
              ) : null}
            </section>
          );
        }) : (
          <p className="mail-sidebar-widget__empty">No mail accounts connected.</p>
        )}
        {notice ? <p className="mail-sidebar-widget__notice">{notice}</p> : null}
      </div>
    </main>
  );
}

createRoot(document.getElementById('mail-sidebar-root') as HTMLElement).render(<MailSidebarWidget />);
