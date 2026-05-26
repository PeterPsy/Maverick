import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  type MailConnection,
  type MailProviderState,
  type MailStatus,
  type MailThread
} from '../../api';
import './styles.css';

const MAILBOXES = ['inbox', 'sent', 'drafts', 'starred', 'trash'];
const MAIL_DATA_RESOURCES = new Set(['connections', 'drafts', 'threads', 'view-state']);
const GMAIL_OAUTH_SECRETS = ['gmail-oauth-client-id', 'gmail-oauth-client-secret'];
const GMAIL_REFRESH_SECRET = 'gmail-refresh-token';

type ConnectionPayload = {
  items: MailConnection[];
  providers?: MailProviderState[];
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
  const [status, setStatus] = useState<MailStatus>({});
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [providers, setProviders] = useState<MailProviderState[]>([]);
  const [threads, setThreads] = useState<MailThread[]>([]);
  const [mailbox, setMailbox] = useState('inbox');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [isMobileLayout, setIsMobileLayout] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [statusPayload, connectionPayload, threadPayload] = await Promise.all([
        callBackend<MailStatus>({ action: MAIL_BACKEND_ACTIONS.status, ...noSecretRequest() }),
        callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() }),
        callBackend<{ items: MailThread[] }>({ action: MAIL_BACKEND_ACTIONS.threadsList, mailbox, max_threads: 50, ...noSecretRequest() })
      ]);
      setStatus(statusPayload);
      setConnections(connectionPayload.items);
      setProviders(connectionPayload.providers || []);
      setThreads(threadPayload.items);
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to load mail.');
    }
  }, [mailbox]);

  useEffect(() => {
    loadWidgetContext().then((context) => {
      const nextMailbox = mailboxFromContext(context);
      if (nextMailbox) {
        setMailbox(nextMailbox);
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
        setIsMobileLayout(isMobileFromContext(payload.context));
        return;
      }
      if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'mail') {
        const nextMailbox = payload.selection?.mailbox;
        if (typeof nextMailbox === 'string' && MAILBOXES.includes(nextMailbox)) {
          setMailbox(nextMailbox);
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

  const connection = connections.find((item) => item.status !== 'disconnected') || connections[0];
  const canUseConnection = Boolean(connection && connection.status !== 'disconnected');
  const gmailProvider = providers.find((provider) => provider.provider === 'gmail');
  const unreadCount = useMemo(() => threads.filter((thread) => thread.unread).length, [threads]);

  async function sync() {
    if (!connection || !canUseConnection) {
      setNotice('No connected mail provider is available to sync.');
      return;
    }
    setBusy(true);
    try {
      await callBackend({
        action: MAIL_BACKEND_ACTIONS.threadsSync,
        connection_id: connection.id,
        ...gmailSecretRequest(connection.id)
      });
      setNotice('Sync completed.');
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Sync failed.');
    } finally {
      setBusy(false);
    }
  }

  async function startGmailOAuth() {
    setBusy(true);
    try {
      const redirectUri = `${window.location.origin}/apps/mail/oauth/callback`;
      const payload = await callBackend<{ status: string; authorization_url?: string; detail?: string }>({
        action: MAIL_BACKEND_ACTIONS.connectionsStartOAuth,
        provider: 'gmail',
        redirect_uri: redirectUri,
        _app_secret_request: {
          logical_names: ['gmail-oauth-client-id'],
          required: false
        }
      });
      if (payload.authorization_url) {
        window.open(payload.authorization_url, '_blank', 'noopener,noreferrer');
      }
      setNotice(payload.detail || `Gmail OAuth status: ${payload.status}`);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Gmail connection failed.');
    } finally {
      setBusy(false);
    }
  }

  function selectMailbox(nextMailbox: string) {
    setMailbox(nextMailbox);
    openMail({ mailbox: nextMailbox });
    if (isMobileLayout) {
      closeShellSidebar();
    }
  }

  return (
    <main className={`mail-sidebar-widget ${isMobileLayout ? 'is-shell-mobile' : ''}`} aria-busy={busy}>
      <div className="mail-sidebar-widget__list">
        <div className="mail-sidebar-widget__account mail-sidebar-widget__row">
          <span className="mail-sidebar-widget__row-icon" aria-hidden="true">M</span>
          <span className="mail-sidebar-widget__row-copy">
            <strong>{connection?.display_name || 'Mail'}</strong>
            <span>{connection?.email_address || 'No connection'}</span>
          </span>
          <small>{status.mode || status.status || 'checking'}</small>
        </div>
        <div className="mail-sidebar-widget__provider mail-sidebar-widget__row">
          <span className="mail-sidebar-widget__row-icon" aria-hidden="true">G</span>
          <span className="mail-sidebar-widget__row-copy">
            <strong>Gmail</strong>
            <span>{gmailProvider?.status || 'needs setup'}</span>
          </span>
          <button type="button" onClick={startGmailOAuth} disabled={busy}>
            Connect
          </button>
        </div>
        <nav className="mail-sidebar-widget__mailboxes" aria-label="Mailboxes">
          {MAILBOXES.map((item) => (
            <button key={item} className={item === mailbox ? 'active' : ''} onClick={() => selectMailbox(item)} type="button">
              <span className="mail-sidebar-widget__row-icon" aria-hidden="true">{item.slice(0, 1).toUpperCase()}</span>
              <span className="mail-sidebar-widget__row-copy">
                <strong>{item}</strong>
                <span>{item === 'inbox' ? `${unreadCount} unread` : 'Mailbox'}</span>
              </span>
              {item === 'inbox' ? <b>{unreadCount}</b> : null}
            </button>
          ))}
        </nav>
        <button className="mail-sidebar-widget__sync mail-sidebar-widget__row" onClick={sync} disabled={busy || !canUseConnection} type="button">
          <span className="mail-sidebar-widget__row-icon" aria-hidden="true">S</span>
          <span className="mail-sidebar-widget__row-copy">
            <strong>Sync</strong>
            <span>Refresh mailbox cache</span>
          </span>
        </button>
        {notice ? <p className="mail-sidebar-widget__notice">{notice}</p> : null}
      </div>
    </main>
  );
}

createRoot(document.getElementById('mail-sidebar-root') as HTMLElement).render(<MailSidebarWidget />);
