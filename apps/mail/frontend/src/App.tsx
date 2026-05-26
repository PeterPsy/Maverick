import { FormEvent, useCallback, useEffect, useState } from 'react';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  type MailConnection,
  type MailDraft,
  type MailProviderState,
  type MailStatus,
  type MailThread
} from './api';
import SlidingPagination from './components/ui/sliding-pagination';

const MAILBOXES = ['inbox', 'sent', 'drafts', 'starred', 'trash'];
const MAIL_DATA_RESOURCES = new Set(['connections', 'drafts', 'threads', 'view-state']);
const GMAIL_OAUTH_SECRETS = ['gmail-oauth-client-id', 'gmail-oauth-client-secret'];
const GMAIL_REFRESH_SECRET = 'gmail-refresh-token';
const THREADS_PAGE_SIZE = 50;

type ConnectionPayload = {
  items: MailConnection[];
  providers?: MailProviderState[];
  required_secrets?: string[];
  callback_path?: string;
};

type SendResult = {
  dry_run?: boolean;
  requires_confirmation?: boolean;
  sent?: boolean;
  message_id?: string;
  draft?: MailDraft;
};

type MailNavigateParams = {
  mailbox?: string;
  query?: string;
  thread?: string;
};

type ThreadListPayload = {
  items: MailThread[];
  limit?: number;
  offset?: number;
  total_count?: number;
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

function notifySelection(selection: Record<string, string | boolean | null>) {
  window.parent?.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'mail',
      selection
    },
    window.location.origin
  );
}

export function App() {
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [providers, setProviders] = useState<MailProviderState[]>([]);
  const [status, setStatus] = useState<MailStatus>({});
  const [threads, setThreads] = useState<MailThread[]>([]);
  const [totalThreads, setTotalThreads] = useState(0);
  const [selectedThread, setSelectedThread] = useState<MailThread | null>(null);
  const [mailbox, setMailbox] = useState('inbox');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState({ to: '', subject: '', body_text: '' });
  const [lastDraft, setLastDraft] = useState<MailDraft | null>(null);
  const [lastSendResult, setLastSendResult] = useState<SendResult | null>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [oauthCompleting, setOauthCompleting] = useState(false);

  const openThread = useCallback(async (threadId: string, connectionId?: string) => {
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.threadsGet,
        thread_id: threadId,
        max_body_chars: 12000,
        ...(connectionId ? gmailSecretRequest(connectionId) : noSecretRequest())
      });
      setSelectedThread(payload.thread);
      notifySelection({ thread: payload.thread.id, mailbox });
    } finally {
      setBusy(false);
    }
  }, [mailbox]);

  const loadThreads = useCallback(async () => {
    const offset = (page - 1) * THREADS_PAGE_SIZE;
    const [statusPayload, connectionPayload, threadPayload] = await Promise.all([
      callBackend<MailStatus>({ action: MAIL_BACKEND_ACTIONS.status, ...noSecretRequest() }),
      callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() }),
      callBackend<ThreadListPayload>({
        action: MAIL_BACKEND_ACTIONS.threadsList,
        mailbox,
        query,
        max_threads: THREADS_PAGE_SIZE,
        offset,
        ...noSecretRequest()
      })
    ]);
    setStatus(statusPayload);
    setConnections(connectionPayload.items);
    setProviders(connectionPayload.providers || []);
    setThreads(threadPayload.items);
    setTotalThreads(threadPayload.total_count ?? threadPayload.items.length);
  }, [mailbox, page, query]);

  useEffect(() => {
    setPage(1);
  }, [mailbox, query]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const threadId = params.get('thread');
    const code = params.get('code');
    const state = params.get('state');
    if (code && state && !oauthCompleting) {
      setOauthCompleting(true);
      callBackend<{ status: string; detail?: string; connection_id?: string }>({
        action: MAIL_BACKEND_ACTIONS.connectionsCompleteOAuth,
        provider: 'gmail',
        code,
        state,
        _app_secret_request: {
          logical_names: ['gmail-oauth-client-id', 'gmail-oauth-client-secret'],
          required: true
        }
      })
        .then((payload) => {
          setNotice(payload.detail || `Gmail OAuth status: ${payload.status}`);
          window.history.replaceState({}, document.title, window.location.pathname);
          if (payload.connection_id) {
            return callBackend({
              action: MAIL_BACKEND_ACTIONS.threadsSync,
              connection_id: payload.connection_id,
              ...gmailSecretRequest(payload.connection_id)
            }).then(() => loadThreads());
          }
          return loadThreads();
        })
        .catch((error: Error) => setNotice(error.message))
        .finally(() => setOauthCompleting(false));
      return;
    }
    if (threadId) {
      openThread(threadId).catch((error: Error) => setNotice(error.message));
    }
  }, [loadThreads, oauthCompleting, openThread]);

  useEffect(() => {
    loadThreads().catch((error: Error) => setNotice(error.message));
  }, [loadThreads]);

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data as { type?: string; owner_app_id?: string; resource?: string; params?: MailNavigateParams };
      if (data?.type === 'maverick.app.navigate') {
        const nextMailbox = data.params?.mailbox;
        if (nextMailbox && MAILBOXES.includes(nextMailbox)) {
          setPage(1);
          setMailbox(nextMailbox);
          setSelectedThread(null);
          notifySelection({ mailbox: nextMailbox, thread: null });
        }
        if (typeof data.params?.query === 'string') {
          setQuery(data.params.query);
        }
        if (data.params?.thread) {
          openThread(data.params.thread).catch((error: Error) => setNotice(error.message));
        }
        return;
      }
      const mailDataChanged =
        (data?.type === 'maverick.app.data-changed' || data?.type === 'maverick.widget.data-changed') &&
        data.owner_app_id === 'mail' &&
        typeof data.resource === 'string' &&
        MAIL_DATA_RESOURCES.has(data.resource);
      if (mailDataChanged) {
        loadThreads().catch((error: Error) => setNotice(error.message));
      }
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [loadThreads, openThread]);

  const connection = connections.find((item) => item.status !== 'disconnected') || connections[0];
  const gmailProvider = providers.find((provider) => provider.provider === 'gmail');
  const activeConnectionCount = connections.filter((item) => item.status !== 'disconnected').length;
  const connectionStatus = connection?.status || status.health_status || status.status || 'not connected';
  const gmailStatus = gmailProvider?.status || (connection?.provider === 'gmail' ? connection.status : 'needs setup');
  const canUseConnection = Boolean(connection && connection.status !== 'disconnected');
  const totalPages = Math.max(1, Math.ceil(totalThreads / THREADS_PAGE_SIZE));
  const visibleStart = totalThreads === 0 ? 0 : (page - 1) * THREADS_PAGE_SIZE + 1;
  const visibleEnd = totalThreads === 0 ? 0 : Math.min(page * THREADS_PAGE_SIZE, totalThreads);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  function closeThread() {
    setSelectedThread(null);
    notifySelection({ mailbox, thread: null });
  }

  async function createDraft(event: FormEvent) {
    event.preventDefault();
    if (!canUseConnection || !connection) {
      setNotice('Connect Gmail before creating drafts.');
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ draft: MailDraft }>({
        action: MAIL_BACKEND_ACTIONS.draftsCreate,
        connection_id: connection?.id,
        thread_id: selectedThread?.id,
        to: draft.to ? [{ email: draft.to }] : [],
        subject: draft.subject,
        body_text: draft.body_text
      });
      setLastDraft(payload.draft);
      setLastSendResult(null);
      setNotice('Draft saved. Preview before confirm.');
      setDraft({ to: '', subject: '', body_text: '' });
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendLastDraft(confirm: boolean) {
    if (!lastDraft) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ result: SendResult }>({
        action: MAIL_BACKEND_ACTIONS.draftsSend,
        draft_id: lastDraft.id,
        confirm,
        ...(confirm ? gmailSecretRequest(lastDraft.connection_id) : noSecretRequest())
      });
      setLastSendResult(payload.result);
      setNotice(confirm ? 'Draft marked sent in the local provider.' : 'Dry-run ready. Confirm only when the user approves send.');
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function markSelected(read: boolean) {
    if (!selectedThread) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.messagesMarkRead,
        thread_id: selectedThread.id,
        read,
        ...gmailSecretRequest(selectedThread.connection_id)
      });
      setSelectedThread(payload.thread);
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function modifySelected(add: string[], remove: string[]) {
    if (!selectedThread) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.labelsModify,
        thread_id: selectedThread.id,
        add,
        remove,
        ...gmailSecretRequest(selectedThread.connection_id)
      });
      setSelectedThread(payload.thread);
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
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
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function syncConnection() {
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
      setNotice('Mailbox sync completed.');
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnectConnection() {
    if (!connection) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ disconnect?: { status?: string; detail?: string } }>({
        action: MAIL_BACKEND_ACTIONS.connectionsDisconnect,
        connection_id: connection.id,
        reason: 'Disconnected from the Mail frontend',
        ...noSecretRequest()
      });
      setSelectedThread(null);
      setLastDraft(null);
      setNotice(payload.disconnect?.detail || `Connection ${payload.disconnect?.status || 'disconnected'}.`);
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={`mail-shell ${selectedThread ? 'is-reading' : 'is-list-only'}`}>
      <section className="thread-column">
        <div className="toolbar">
          <label className="mail-search">
            <span className="mail-search__icon" aria-hidden="true" />
            <input aria-label="Search in Mail" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search in Mail" />
          </label>
          <div className="mail-page-controls" aria-label="Mail pagination">
            <span className="mail-page-range">{visibleStart}-{visibleEnd}</span>
            {totalPages > 1 ? (
              <SlidingPagination
                totalPages={totalPages}
                currentPage={page}
                onPageChange={setPage}
                maxVisiblePages={7}
              />
            ) : null}
          </div>
        </div>
        <section className="connection-panel" aria-label="Mail connection controls">
          <div className="connection-panel__summary">
            <div className="connection-panel__item">
              <span>Connections</span>
              <strong>{activeConnectionCount}/{connections.length || status.connection_count || 0}</strong>
              <small>{connectionStatus}</small>
            </div>
            <div className="connection-panel__item">
              <span>Gmail</span>
              <strong>{gmailProvider?.configured === false ? 'Not configured' : gmailStatus}</strong>
              <small>{connection?.email_address || 'No account'}</small>
            </div>
          </div>
          <div className="connection-panel__actions">
            <button type="button" onClick={startGmailOAuth} disabled={busy}>
              {gmailProvider?.connected ? 'Reconnect Gmail' : 'Connect Gmail'}
            </button>
            <button type="button" onClick={syncConnection} disabled={busy || !canUseConnection}>
              Sync
            </button>
            <button
              type="button"
              className="connection-panel__disconnect"
              onClick={disconnectConnection}
              disabled={busy || !connection || connection.status === 'disconnected'}
            >
              Disconnect
            </button>
          </div>
        </section>
        <div className="thread-list">
          {threads.length === 0 ? (
            <div className="thread-empty">
              {canUseConnection ? 'No threads match this view.' : 'Connect Gmail or bootstrap a mock provider from CLI/MCP to load mail.'}
            </div>
          ) : null}
          {threads.map((thread) => (
            <button key={thread.id} className={`thread-row ${selectedThread?.id === thread.id ? 'selected' : ''}`} onClick={() => openThread(thread.id, thread.connection_id)}>
              <span className="thread-title">{thread.subject}</span>
              <span className="thread-meta">{thread.participants.map((person) => person.name || person.email).join(', ')}</span>
              <span className="thread-snippet">{thread.snippet}</span>
              <span className="label-strip">{thread.labels.join(' / ')}</span>
            </button>
          ))}
        </div>
        {!selectedThread && notice ? <div className="notice">{notice}</div> : null}
      </section>

      {selectedThread ? (
        <section className="reader-column">
          <header className="reader-header">
            <div>
              <h1>{selectedThread.subject}</h1>
              <p>{selectedThread.participants.map((person) => person.name || person.email).join(', ')}</p>
            </div>
            <div className="reader-actions">
              <button type="button" onClick={() => markSelected(selectedThread.unread)} disabled={busy}>
                {selectedThread.unread ? 'Mark read' : 'Mark unread'}
              </button>
              <button type="button" onClick={() => modifySelected([], ['inbox'])} disabled={busy}>
                Archive
              </button>
              <button type="button" onClick={() => modifySelected(['trash'], ['inbox'])} disabled={busy}>
                Trash
              </button>
              <button type="button" onClick={() => openThread(selectedThread.id, selectedThread.connection_id)} disabled={busy}>
                Refresh
              </button>
              <button type="button" className="reader-close" onClick={closeThread} aria-label="Close mail">
                X
              </button>
            </div>
          </header>
          <div className="message-stack">
            {(selectedThread.messages || []).map((message) => (
              <article key={message.id} className="message">
                <div className="message-head">
                  <strong>{message.sender.name || message.sender.email}</strong>
                  <span>{new Date(message.sent_at).toLocaleString()}</span>
                </div>
                <p>{message.body_text}</p>
                {message.has_attachments ? <small>Attachments available after provider fetch is enabled.</small> : null}
              </article>
            ))}
          </div>
          {canUseConnection && connection ? (
            <form className="composer" onSubmit={createDraft}>
              <input value={draft.to} onChange={(event) => setDraft({ ...draft, to: event.target.value })} placeholder="Recipient email" required />
              <input value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} placeholder="Subject" required />
              <textarea value={draft.body_text} onChange={(event) => setDraft({ ...draft, body_text: event.target.value })} placeholder="Write a draft" required />
              <div className="composer-actions">
                <button type="submit" disabled={busy}>Save draft</button>
                <button type="button" onClick={() => sendLastDraft(false)} disabled={busy || !lastDraft}>Preview send</button>
                <button type="button" onClick={() => sendLastDraft(true)} disabled={busy || !lastDraft}>Confirm send</button>
              </div>
            </form>
          ) : null}
          {lastDraft ? <p className="draft-note">Last draft: {lastDraft.subject}</p> : null}
          {lastSendResult?.dry_run ? <p className="draft-note">Dry-run prepared for draft {lastSendResult.draft?.id}.</p> : null}
          {lastSendResult?.sent ? <p className="draft-note">Sent locally as message {lastSendResult.message_id}.</p> : null}
          {notice ? <div className="notice">{notice}</div> : null}
        </section>
      ) : null}
    </main>
  );
}
