import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AuditEvent, GmailMessage, Suggestion, ThreadSummary, callBackend, clearOAuthSession, loadOAuthSession, saveOAuthSession } from './api';
import './styles/main.css';

type Mailbox = 'inbox' | 'promotions' | 'updates' | 'starred' | 'sent' | 'important' | 'spam' | 'all';

const mailboxItems: Array<{ id: Mailbox; icon: string; label: string }> = [
  { id: 'inbox', icon: 'inbox', label: 'Inbox' },
  { id: 'promotions', icon: 'local_offer', label: 'Promotions' },
  { id: 'updates', icon: 'info', label: 'Updates' },
  { id: 'starred', icon: 'star', label: 'Starred' },
  { id: 'sent', icon: 'send', label: 'Sent' },
  { id: 'important', icon: 'label_important', label: 'Important' },
  { id: 'spam', icon: 'report', label: 'Spam' },
  { id: 'all', icon: 'mail', label: 'All Mail' }
];

function App() {
  const [query, setQuery] = useState('');
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [selected, setSelected] = useState<ThreadSummary | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [draftBody, setDraftBody] = useState('');
  const [clientId, setClientId] = useState(loadOAuthSession().clientId);
  const [clientSecret, setClientSecret] = useState(loadOAuthSession().clientSecret);
  const [loginEmail, setLoginEmail] = useState(loadOAuthSession().loginEmail);
  const [accessToken, setAccessToken] = useState(loadOAuthSession().accessToken);
  const [accountEmail, setAccountEmail] = useState(loadOAuthSession().email);
  const [diagnosticUrl, setDiagnosticUrl] = useState('');
  const [pendingVerifier, setPendingVerifier] = useState('');
  const [pendingState, setPendingState] = useState('');
  const [showSetup, setShowSetup] = useState(false);
  const [isLoadingLatest, setIsLoadingLatest] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [latestSource, setLatestSource] = useState('');
  const [nextPageToken, setNextPageToken] = useState('');
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMoreCached, setHasMoreCached] = useState(false);
  const [mailbox, setMailbox] = useState<Mailbox>('inbox');
  const [viewMode, setViewMode] = useState<'list' | 'detail' | 'review'>('list');
  const [status, setStatus] = useState('Checking connection');
  const [error, setError] = useState('');
  const clientIdRef = useRef<HTMLInputElement>(null);
  const clientSecretRef = useRef<HTMLInputElement>(null);
  const loginEmailRef = useRef<HTMLInputElement>(null);

  function currentOAuthInputs() {
    const values = {
      clientId: (clientIdRef.current?.value || clientId).trim(),
      clientSecret: (clientSecretRef.current?.value || clientSecret).trim(),
      loginEmail: (loginEmailRef.current?.value || loginEmail).trim()
    };
    setClientId(values.clientId);
    setClientSecret(values.clientSecret);
    setLoginEmail(values.loginEmail);
    return values;
  }

  function validateClientId(value: string): string {
    if (!value) return 'Google OAuth client ID is required.';
    if (!value.endsWith('.apps.googleusercontent.com')) return 'Client ID must end with .apps.googleusercontent.com. Do not use Maverick username/password here.';
    return '';
  }

  async function refreshStatus() {
    const payload = await callBackend<{ connected_accounts: unknown[] }>({ action: 'connection.status' });
    setStatus(accountEmail || payload.connected_accounts.length ? 'Google Workspace account connected' : 'OAuth connection pending');
  }

  async function generateLoginUrl() {
    setError('');
    const inputs = currentOAuthInputs();
    const clientIdError = validateClientId(inputs.clientId);
    if (clientIdError) {
      setError(clientIdError);
      return;
    }
    if (!inputs.clientSecret) {
      setError('Google OAuth client secret is required.');
      return;
    }
    saveOAuthSession({ clientId: inputs.clientId, clientSecret: inputs.clientSecret, loginEmail: inputs.loginEmail });
    const redirectUri = `${window.location.origin}/apps/gmail-app/`;
    const payload = await callBackend<{ authorization_url: string; code_verifier: string; state: string }>({
      action: 'oauth.authorization_url',
      client_id: inputs.clientId,
      redirect_uri: redirectUri,
      login_hint: inputs.loginEmail
    });
    setPendingVerifier(payload.code_verifier);
    setPendingState(payload.state);
    setDiagnosticUrl(payload.authorization_url);
  }

  function persistOAuthState() {
    sessionStorage.setItem('gmail_app_code_verifier', pendingVerifier);
    sessionStorage.setItem('gmail_app_oauth_state', pendingState);
  }

  async function finishOAuthFromCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const returnedState = params.get('state');
    if (!code) return;
    const expectedState = sessionStorage.getItem('gmail_app_oauth_state') || '';
    const codeVerifier = sessionStorage.getItem('gmail_app_code_verifier') || '';
    if (!returnedState || returnedState !== expectedState || !codeVerifier) {
      setError('OAuth state mismatch. Start Gmail login again.');
      return;
    }
    const session = loadOAuthSession();
    const payload = await callBackend<{ token: { access_token: string }; account: { email: string } }>({
      action: 'oauth.exchange',
      client_id: session.clientId,
      client_secret: session.clientSecret,
      redirect_uri: `${window.location.origin}/apps/gmail-app/`,
      code,
      code_verifier: codeVerifier
    });
    saveOAuthSession({ accessToken: payload.token.access_token, email: payload.account.email });
    setAccessToken(payload.token.access_token);
    setAccountEmail(payload.account.email);
    setStatus('Google Workspace account connected');
    returnToShellAfterOAuth();
  }

  function disconnect() {
    clearOAuthSession();
    setAccessToken('');
    setAccountEmail('');
    setStatus('OAuth connection pending');
  }

  async function search() {
    setError('');
    setLatestSource('');
    const payload = await callBackend<{ threads: ThreadSummary[] }>({ action: 'threads.search', query, ...(accessToken ? { access_token: accessToken } : {}) });
    setThreads(payload.threads);
    if (payload.threads[0]) setSelected(payload.threads[0]);
  }

  async function loadLatest(forceRefresh = false) {
    await loadMailbox(mailbox, { forceRemote: forceRefresh });
  }

  async function loadSpam(forceRefresh = false) {
    await loadMailbox('spam', { forceRemote: forceRefresh });
  }

  async function loadMailbox(targetMailbox = mailbox, options: { forceRemote?: boolean; pageToken?: string; offset?: number } = {}) {
    setError('');
    const requestedOffset = options.offset ?? 0;
    const isMore = Boolean(options.pageToken) || requestedOffset > 0;
    const isRemoteSync = Boolean(options.forceRemote || options.pageToken);
    if (isMore) {
      setIsLoadingMore(true);
    } else if (isRemoteSync) {
      setIsLoadingLatest(true);
      setNextPageToken('');
      setNextOffset(0);
      setHasMoreCached(false);
    } else {
      setNextPageToken('');
      setNextOffset(0);
      setHasMoreCached(false);
    }
    try {
      const request = mailboxRequest(targetMailbox);
      const payload = await callBackend<{ threads: ThreadSummary[]; source: string; next_page_token?: string; next_offset?: number; has_more?: boolean }>({
        action: 'threads.page',
        limit: 50,
        offset: requestedOffset,
        page_token: options.pageToken || '',
        force_remote: Boolean(options.forceRemote || options.pageToken),
        ...request,
        ...(accessToken ? { access_token: accessToken } : {})
      });
      setThreads((current) => mergeThreads(current, payload.threads));
      setNextPageToken(payload.next_page_token || '');
      setNextOffset(payload.next_offset || (isMore ? requestedOffset + payload.threads.length : payload.threads.length));
      setHasMoreCached(Boolean(payload.has_more && !payload.next_page_token));
      setLatestSource(payload.source === 'cache' ? 'Cached' : 'Synced');
      if (!selected && payload.threads[0]) setSelected(payload.threads[0]);
      await loadAudit();
      return payload;
    } finally {
      setIsLoadingLatest(false);
      setIsLoadingMore(false);
    }
  }

  async function summarize(thread: ThreadSummary) {
    setError('');
    const payload = await callBackend<{ suggestions: Suggestion[] }>({ action: 'threads.summarize', thread_id: thread.id });
    setSuggestions(payload.suggestions);
  }

  async function openRelationshipReview() {
    setError('');
    const payload = await callBackend<{ suggestions: Suggestion[] }>({ action: 'suggestions.list', status: 'pending', limit: 100 });
    setSuggestions(payload.suggestions);
    setViewMode('review');
  }

  async function openThread(thread: ThreadSummary) {
    setSelected({ ...thread, is_unread: false });
    setThreads((current) => current.map((item) => item.id === thread.id ? { ...item, is_unread: false } : item));
    setViewMode('detail');
    if (!thread.is_unread && thread.messages?.length) return;
    try {
      const payload = await callBackend<{ thread: ThreadSummary }>({ action: 'threads.mark_read', thread_id: thread.id });
      setSelected(payload.thread);
      setThreads((current) => current.map((item) => item.id === thread.id ? { ...item, ...payload.thread, is_unread: false } : item));
      await loadAudit();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function saveSuggestion(suggestion: Suggestion) {
    await callBackend({
      action: 'suggestions.mark_reviewed',
      suggestion_id: suggestion.id,
      decision: 'reviewed'
    });
    setSuggestions((current) => current.filter((item) => item.id !== suggestion.id));
    await loadAudit();
  }

  async function prepareReply() {
    if (!selected) return;
    const payload = await callBackend<{ draft: { body_text: string } }>({
      action: 'compose.prepare_reply',
      thread_id: selected.id,
      instruction: draftBody || 'Grazie, procedo e ti aggiorno a breve.'
    });
    setDraftBody(payload.draft.body_text);
    await loadAudit();
  }

  async function loadAudit() {
    const payload = await callBackend<{ events: AuditEvent[] }>({ action: 'audit.recent', limit: 12 });
    setAudit(payload.events);
  }

  useEffect(() => {
    finishOAuthFromCallback().catch((err: Error) => setError(err.message));
    refreshStatus().catch((err: Error) => setError(err.message));
    loadAudit().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (viewMode === 'list') {
      loadMailbox(mailbox).catch((err: Error) => setError(err.message));
    }
  }, [mailbox]);

  const filteredThreads = useMemo(() => {
    return threads.filter((thread) => {
      if (mailbox === 'all') return true;
      if (mailbox === 'sent') return thread.labels?.includes('SENT');
      if (mailbox === 'important') return thread.labels?.includes('IMPORTANT');
      if (mailbox === 'starred') return thread.labels?.includes('STARRED');
      if (mailbox === 'promotions') return thread.labels?.includes('CATEGORY_PROMOTIONS');
      if (mailbox === 'updates') return thread.labels?.includes('CATEGORY_UPDATES');
      if (mailbox === 'spam') return thread.labels?.includes('SPAM');
      if (thread.labels?.includes('SPAM') || thread.labels?.includes('TRASH')) return false;
      return (thread.labels?.includes('INBOX') || !thread.labels?.includes('SENT'))
        && !thread.labels?.includes('CATEGORY_PROMOTIONS')
        && !thread.labels?.includes('CATEGORY_UPDATES');
    });
  }, [mailbox, threads]);

  const unreadCount = useMemo(() => threads.filter((thread) => thread.is_unread && !thread.labels?.includes('CATEGORY_PROMOTIONS') && !thread.labels?.includes('CATEGORY_UPDATES') && !thread.labels?.includes('SPAM') && !thread.labels?.includes('TRASH')).length, [threads]);
  const promotionsCount = useMemo(() => threads.filter((thread) => thread.labels?.includes('CATEGORY_PROMOTIONS')).length, [threads]);
  const updatesCount = useMemo(() => threads.filter((thread) => thread.labels?.includes('CATEGORY_UPDATES')).length, [threads]);
  const sentCount = useMemo(() => threads.filter((thread) => thread.labels?.includes('SENT')).length, [threads]);
  const spamCount = useMemo(() => threads.filter((thread) => thread.labels?.includes('SPAM')).length, [threads]);
  const setupButtonLabel = accountEmail ? accountEmail : 'Connect Gmail';

  return (
    <main className="gmail-shell">
      <header className="gmail-topbar">
        <button type="button" className="ghost-icon" aria-label="Menu">
          <span className="material-symbols-rounded" aria-hidden="true">menu</span>
        </button>
        <div className="brand-lockup" aria-label="Gmail App">
          <span className="brand-mark material-symbols-rounded" aria-hidden="true">mail</span>
          <strong>Gmail App</strong>
        </div>
        <form className="search-box" onSubmit={(event) => { event.preventDefault(); search().catch((err: Error) => setError(err.message)); }}>
          <span className="material-symbols-rounded" aria-hidden="true">search</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search mail" />
          {query ? (
            <button type="button" className="ghost-icon small" onClick={() => setQuery('')} aria-label="Clear search">
              <span className="material-symbols-rounded" aria-hidden="true">close</span>
            </button>
          ) : null}
        </form>
        <div className="top-actions">
          <button type="button" className="ghost-icon" onClick={() => refreshStatus().catch((err: Error) => setError(err.message))} aria-label="Refresh status">
            <span className="material-symbols-rounded" aria-hidden="true">refresh</span>
          </button>
          <button type="button" className="account-chip" onClick={() => setShowSetup(true)} title="Gmail setup">
            <span className="material-symbols-rounded" aria-hidden="true">{accountEmail ? 'check_circle' : 'settings'}</span>
            <span>{setupButtonLabel}</span>
          </button>
        </div>
      </header>

      {error ? <div className="error">{error}</div> : null}

      {showSetup ? <SetupModal
        accessToken={accessToken}
        clientId={clientId}
        clientIdRef={clientIdRef}
        clientSecret={clientSecret}
        clientSecretRef={clientSecretRef}
        diagnosticUrl={diagnosticUrl}
        disconnect={disconnect}
        generateLoginUrl={() => generateLoginUrl().catch((err: Error) => setError(err.message))}
        loginEmail={loginEmail}
        loginEmailRef={loginEmailRef}
        persistOAuthState={persistOAuthState}
        setClientId={setClientId}
        setClientSecret={setClientSecret}
        setLoginEmail={setLoginEmail}
        setShowSetup={setShowSetup}
      /> : null}

      <section className="mail-layout">
        <aside className="mail-sidebar" aria-label="Mail folders">
          <button type="button" className="compose-button">
            <span className="material-symbols-rounded" aria-hidden="true">edit</span>
            Compose
          </button>
          <nav>
            {mailboxItems.map((item) => (
              <button key={item.id} type="button" className={viewMode === 'list' && mailbox === item.id ? 'nav-item active' : 'nav-item'} onClick={() => { setMailbox(item.id); setViewMode('list'); }}>
                <span className="material-symbols-rounded" aria-hidden="true">{item.icon}</span>
                <span>{item.label}</span>
                {item.id === 'inbox' && unreadCount ? <strong>{unreadCount}</strong> : null}
                {item.id === 'promotions' && promotionsCount ? <strong>{promotionsCount}</strong> : null}
                {item.id === 'updates' && updatesCount ? <strong>{updatesCount}</strong> : null}
                {item.id === 'sent' && sentCount ? <strong>{sentCount}</strong> : null}
                {item.id === 'spam' && spamCount ? <strong>{spamCount}</strong> : null}
              </button>
            ))}
          </nav>
          <div className="sidebar-section">
            <span>Labels</span>
            <button type="button" className={viewMode === 'review' ? 'nav-item active' : 'nav-item quiet'} onClick={() => openRelationshipReview().catch((err: Error) => setError(err.message))}>
              <span className="material-symbols-rounded" aria-hidden="true">sell</span>
              <span>Relationship review</span>
              {suggestions.length ? <strong>{suggestions.length}</strong> : null}
            </button>
          </div>
        </aside>

        <section className={viewMode === 'detail' ? 'mail-main detail-mode' : 'mail-main'} aria-label="Inbox">
          <div className="mail-toolbar">
            {viewMode !== 'list' ? (
              <button type="button" className="ghost-icon" onClick={() => setViewMode('list')} aria-label="Back to inbox">
                <span className="material-symbols-rounded" aria-hidden="true">arrow_back</span>
              </button>
            ) : (
              <label className="select-all" aria-label="Select all visible messages">
                <input type="checkbox" />
                <span></span>
              </label>
            )}
            <button type="button" className="ghost-icon" disabled={isLoadingLatest} onClick={() => loadLatest(true).catch((err: Error) => setError(err.message))} aria-label="Refresh Gmail">
              <span className={isLoadingLatest ? 'material-symbols-rounded spinning' : 'material-symbols-rounded'} aria-hidden="true">{isLoadingLatest ? 'progress_activity' : 'refresh'}</span>
            </button>
            <button type="button" className="toolbar-button" disabled={isLoadingLatest} onClick={() => loadLatest(true).catch((err: Error) => setError(err.message))}>
              <span className="material-symbols-rounded" aria-hidden="true">sync</span>
              Sync
            </button>
            {viewMode === 'detail' && selected ? (
              <>
                <button type="button" className="ghost-icon" onClick={() => summarize(selected).catch((err: Error) => setError(err.message))} aria-label="Review relationship">
                  <span className="material-symbols-rounded" aria-hidden="true">person_add</span>
                </button>
                <button type="button" className="ghost-icon" onClick={() => prepareReply().catch((err: Error) => setError(err.message))} aria-label="Reply">
                  <span className="material-symbols-rounded" aria-hidden="true">reply</span>
                </button>
              </>
            ) : null}
            <button type="button" className="ghost-icon" onClick={() => search().catch((err: Error) => setError(err.message))} aria-label="Search">
              <span className="material-symbols-rounded" aria-hidden="true">search</span>
            </button>
            <div className="mail-range">
              <span>{viewMode === 'review' ? `${suggestions.length} relationship items` : `${filteredThreads.length ? `1-${filteredThreads.length}` : '0'} of ${threads.length}`}</span>
              {latestSource ? <em>{latestSource}</em> : null}
            </div>
          </div>

          {viewMode === 'review' ? (
            <RelationshipReviewView
              accountEmail={accountEmail}
              openThreadById={(threadId) => {
                const thread = threads.find((item) => item.id === threadId);
                if (thread) openThread(thread).catch((err: Error) => setError(err.message));
              }}
              saveSuggestion={saveSuggestion}
              suggestions={suggestions}
            />
          ) : viewMode === 'detail' && selected ? (
            <ThreadDetail
              accountEmail={accountEmail}
              draftBody={draftBody}
              saveSuggestion={saveSuggestion}
              selected={selected}
              setDraftBody={setDraftBody}
              suggestions={suggestions}
            />
          ) : (
            <div className="message-list">
              {isLoadingLatest ? <InboxLoader /> : null}
              {filteredThreads.map((thread) => (
                <button key={thread.id} type="button" className={`${selected?.id === thread.id ? 'message-row selected' : 'message-row'} ${thread.is_unread ? 'unread' : ''}`} onClick={() => openThread(thread)}>
                  <span className="row-checkbox" aria-hidden="true"></span>
                  <span className="material-symbols-rounded row-star" aria-hidden="true">{thread.labels?.includes('STARRED') ? 'star' : 'star_border'}</span>
                  <span className="row-important material-symbols-rounded" aria-hidden="true">{thread.labels?.includes('IMPORTANT') ? 'label_important' : 'label_important_outline'}</span>
                  <span className="sender">{displaySender(thread, accountEmail)}</span>
                  <span className="subject-line">
                    <strong>{thread.subject || '(no subject)'}</strong>
                    <span>{thread.snippet}</span>
                  </span>
                  <span className="row-labels">
                    {thread.labels?.includes('SENT') ? <em>Sent</em> : null}
                    {thread.labels?.includes('IMPORTANT') ? <em>Important</em> : null}
                  </span>
                  <time>{formatThreadDate(thread.updated_at)}</time>
                </button>
              ))}
              {!filteredThreads.length && !isLoadingLatest ? (
                <div className="empty-inbox">
                  <span className="material-symbols-rounded" aria-hidden="true">inbox</span>
                  <strong>No mail loaded</strong>
                  <p>Press Sync to load Gmail threads into this app cache.</p>
                </div>
              ) : null}
              {viewMode === 'list' && filteredThreads.length ? (
                <div className="load-more-row">
                  <button type="button" className="toolbar-button" disabled={isLoadingMore || (!nextPageToken && !hasMoreCached)} onClick={() => loadMailbox(mailbox, nextPageToken ? { forceRemote: true, pageToken: nextPageToken } : { offset: nextOffset }).catch((err: Error) => setError(err.message))}>
                    <span className={isLoadingMore ? 'material-symbols-rounded spinning' : 'material-symbols-rounded'} aria-hidden="true">{isLoadingMore ? 'progress_activity' : 'expand_more'}</span>
                    {nextPageToken || hasMoreCached ? 'Load more' : 'No more mail'}
                  </button>
                </div>
              ) : null}
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

type SetupModalProps = {
  accessToken: string;
  clientId: string;
  clientIdRef: React.RefObject<HTMLInputElement | null>;
  clientSecret: string;
  clientSecretRef: React.RefObject<HTMLInputElement | null>;
  diagnosticUrl: string;
  disconnect: () => void;
  generateLoginUrl: () => Promise<void>;
  loginEmail: string;
  loginEmailRef: React.RefObject<HTMLInputElement | null>;
  persistOAuthState: () => void;
  setClientId: (value: string) => void;
  setClientSecret: (value: string) => void;
  setLoginEmail: (value: string) => void;
  setShowSetup: (value: boolean) => void;
};

type ThreadDetailProps = {
  accountEmail: string;
  draftBody: string;
  saveSuggestion: (suggestion: Suggestion) => Promise<void>;
  selected: ThreadSummary;
  setDraftBody: (value: string) => void;
  suggestions: Suggestion[];
};

type RelationshipReviewViewProps = {
  accountEmail: string;
  openThreadById: (threadId: string) => void;
  saveSuggestion: (suggestion: Suggestion) => Promise<void>;
  suggestions: Suggestion[];
};

function RelationshipReviewView(props: RelationshipReviewViewProps) {
  const visibleSuggestions = useMemo(() => {
    return props.suggestions.filter((suggestion) => normalizeEmail(suggestion.email) !== normalizeEmail(props.accountEmail));
  }, [props.accountEmail, props.suggestions]);
  const activities = visibleSuggestions.filter((suggestion) => suggestion.kind === 'activity');
  const contacts = visibleSuggestions.filter((suggestion) => suggestion.kind === 'contact');

  return (
    <div className="relationship-review-view">
      <header className="review-title">
        <div>
          <span className="material-symbols-rounded" aria-hidden="true">sell</span>
          <h1>Relazioni individuate</h1>
        </div>
        <p>{visibleSuggestions.length} elementi trovati nelle email. Rivedi gli elementi utili e poi collegali tramite reference surface generiche.</p>
      </header>

      {activities.length ? (
        <ReviewSection
          emptyText=""
          icon="task_alt"
          items={activities}
          label="Attività"
          saveSuggestion={props.saveSuggestion}
          subtitle="Conversazioni o follow-up da registrare come attività."
          title="Attività da salvare"
          openThreadById={props.openThreadById}
        />
      ) : null}

      {contacts.length ? (
        <ReviewSection
          emptyText=""
          icon="person_add"
          items={contacts}
          label="Contatti"
          saveSuggestion={props.saveSuggestion}
          subtitle="Persone trovate nelle conversazioni email."
          title="Contatti da aggiungere"
          openThreadById={props.openThreadById}
        />
      ) : null}

      {!visibleSuggestions.length ? (
        <div className="empty-inbox">
          <span className="material-symbols-rounded" aria-hidden="true">contacts</span>
          <strong>Nessun elemento da salvare</strong>
          <p>Apri una mail e premi il pulsante relazioni nella toolbar per creare proposte da rivedere qui.</p>
        </div>
      ) : null}
    </div>
  );
}

type ReviewSectionProps = {
  emptyText: string;
  icon: string;
  items: Suggestion[];
  label: string;
  openThreadById: (threadId: string) => void;
  saveSuggestion: (suggestion: Suggestion) => Promise<void>;
  subtitle: string;
  title: string;
};

function ReviewSection(props: ReviewSectionProps) {
  return (
    <section className="review-section">
      <header>
        <div>
          <span className="material-symbols-rounded" aria-hidden="true">{props.icon}</span>
          <div>
            <h2>{props.title}</h2>
            <p>{props.subtitle}</p>
          </div>
        </div>
        <strong>{props.items.length}</strong>
      </header>
      <div className="review-list">
        {props.items.map((suggestion) => (
          <article key={suggestion.id} className="review-item">
            <div className="review-item-main">
              <span>{props.label}</span>
              <strong>{suggestion.title}</strong>
              {suggestion.email ? <small>{suggestion.email}</small> : null}
              <p>{friendlyNote(suggestion.note)}</p>
            </div>
            <div className="review-item-actions">
              <button type="button" className="secondary-button open-email-button" onClick={() => props.openThreadById(suggestion.thread_id)}>
                <span className="material-symbols-rounded" aria-hidden="true">mail</span>
                Email
              </button>
              <button type="button" onClick={() => props.saveSuggestion(suggestion).catch(() => undefined)}>
                <span className="material-symbols-rounded" aria-hidden="true">check</span>
                Segna rivisto
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ThreadDetail(props: ThreadDetailProps) {
  const messages = props.selected.messages?.length ? props.selected.messages : [threadFallbackMessage(props.selected)];
  return (
    <div className="thread-detail-view">
      <div className="detail-subject-row">
        <h1>{props.selected.subject || '(no subject)'}</h1>
        <div className="detail-labels">
          {props.selected.labels?.includes('SENT') ? <span>Sent</span> : null}
          {props.selected.labels?.includes('INBOX') ? <span>Inbox</span> : null}
          {props.selected.labels?.includes('IMPORTANT') ? <span>Important</span> : null}
        </div>
      </div>

      <div className="conversation-stack">
        {messages.map((message, index) => (
          <article key={message.id || `${props.selected.id}-${index}`} className="gmail-message-card">
            <div className="avatar" aria-hidden="true">{initialFor(message.from_email || displaySender(props.selected, props.accountEmail))}</div>
            <div className="gmail-message-content">
              <header className="gmail-message-header">
                <div>
                  <strong>{message.from_email || displaySender(props.selected, props.accountEmail)}</strong>
                  <span>to {formatRecipientLine(message.to_emails, props.accountEmail)}</span>
                </div>
                <time>{formatFullDate(message.received_at || props.selected.updated_at)}</time>
              </header>
              <p>{message.body_text || message.snippet || props.selected.snippet}</p>
            </div>
          </article>
        ))}
      </div>

      <div className="reply-card">
        <div className="avatar muted" aria-hidden="true">{initialFor(props.accountEmail || 'me')}</div>
        <textarea className="reply-box" value={props.draftBody} onChange={(event) => props.setDraftBody(event.target.value)} placeholder="Write reply instructions or draft body" />
      </div>

      <div className="relationship-review-panel">
        <header>
          <span className="material-symbols-rounded" aria-hidden="true">contacts</span>
          <strong>Relationship review</strong>
        </header>
        <div className="relationship-list">
          {props.suggestions.map((suggestion) => (
            <article key={suggestion.id} className="suggestion">
              <span>{suggestion.kind}</span>
              <strong>{suggestion.title}</strong>
              <p>{suggestion.note}</p>
              <button type="button" onClick={() => props.saveSuggestion(suggestion).catch(() => undefined)}>
                <span className="material-symbols-rounded" aria-hidden="true">check</span>
                Save
              </button>
            </article>
          ))}
          {!props.suggestions.length ? <p className="rail-empty">Click the relationship icon in the toolbar to extract relationship candidates from this conversation.</p> : null}
        </div>
      </div>
    </div>
  );
}

function SetupModal(props: SetupModalProps) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Google OAuth setup">
      <section className="oauth-panel" aria-label="Google OAuth setup">
        <header className="oauth-heading">
          <h2>Google OAuth setup</h2>
          <p>Redirect URI: <code>{`${window.location.origin}/apps/gmail-app/`}</code></p>
        </header>
        <label>
          <span>Client ID</span>
          <input ref={props.clientIdRef} value={props.clientId} onChange={(event) => props.setClientId(event.target.value)} placeholder="Paste Google OAuth client ID" autoComplete="off" spellCheck={false} />
        </label>
        <label>
          <span>Client secret</span>
          <input ref={props.clientSecretRef} value={props.clientSecret} onChange={(event) => props.setClientSecret(event.target.value)} placeholder="Paste Google OAuth client secret" type="password" autoComplete="off" spellCheck={false} />
        </label>
        <label>
          <span>Login email</span>
          <input ref={props.loginEmailRef} value={props.loginEmail} onChange={(event) => props.setLoginEmail(event.target.value)} placeholder="piero@versytechnologies.com" autoComplete="email" spellCheck={false} />
        </label>
        <div className="oauth-actions">
          <button type="button" onClick={() => props.generateLoginUrl()}>
            <span className="material-symbols-rounded" aria-hidden="true">link</span>
            Generate login URL
          </button>
          <button type="button" className="secondary-button" onClick={() => props.setShowSetup(false)}>
            <span className="material-symbols-rounded" aria-hidden="true">close</span>
            Close
          </button>
          {props.accessToken ? (
            <button type="button" className="secondary-button" onClick={props.disconnect}>
              <span className="material-symbols-rounded" aria-hidden="true">logout</span>
              Disconnect
            </button>
          ) : null}
        </div>
        {props.diagnosticUrl ? (
          <div className="diagnostic-block">
            <textarea className="diagnostic-url" value={props.diagnosticUrl} readOnly aria-label="OAuth diagnostic URL" />
            <a className="oauth-login-button" href={props.diagnosticUrl} target="_top" onClick={props.persistOAuthState}>
              <span className="material-symbols-rounded" aria-hidden="true">login</span>
              Open exact Google login URL
            </a>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function InboxLoader() {
  return (
    <div className="inbox-loader">
      {Array.from({ length: 8 }).map((_, index) => <span key={index}></span>)}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);

type MailboxRequest = {
  query: string;
  include_system_labels?: boolean;
  required_label?: string;
  excluded_labels?: string[];
};

function mailboxRequest(mailbox: Mailbox): MailboxRequest {
  if (mailbox === 'sent') return { query: 'in:sent', required_label: 'SENT' };
  if (mailbox === 'important') return { query: 'is:important', required_label: 'IMPORTANT' };
  if (mailbox === 'starred') return { query: 'is:starred', required_label: 'STARRED' };
  if (mailbox === 'promotions') return { query: 'category:promotions', required_label: 'CATEGORY_PROMOTIONS' };
  if (mailbox === 'updates') return { query: 'category:updates', required_label: 'CATEGORY_UPDATES' };
  if (mailbox === 'spam') return { query: 'in:spam', include_system_labels: true, required_label: 'SPAM' };
  if (mailbox === 'inbox') return { query: 'in:inbox -category:promotions -category:updates', required_label: 'INBOX', excluded_labels: ['CATEGORY_PROMOTIONS', 'CATEGORY_UPDATES', 'SPAM', 'TRASH'] };
  return { query: '' };
}

function mergeThreads(current: ThreadSummary[], incoming: ThreadSummary[]): ThreadSummary[] {
  const byId = new Map(current.map((thread) => [thread.id, thread]));
  incoming.forEach((thread) => byId.set(thread.id, { ...byId.get(thread.id), ...thread }));
  return Array.from(byId.values()).sort((a, b) => timestampValue(b.updated_at) - timestampValue(a.updated_at));
}

function timestampValue(value: string): number {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function formatThreadDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatFullDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
}

function displaySender(thread: ThreadSummary, accountEmail: string): string {
  const self = normalizeEmail(accountEmail);
  const labels = thread.labels || [];
  if (labels.includes('SENT')) {
    const recipient = firstExternal(thread.to_emails || [], self) || firstExternal(thread.participants || [], self);
    return recipient ? `To: ${recipient}` : 'To: recipient';
  }
  const from = normalizeEmail(thread.from_email || '');
  if (from && from !== self) return from;
  return firstExternal(thread.participants || [], self) || from || thread.participants?.[0] || 'Unknown sender';
}

function firstExternal(values: string[], self: string): string {
  return values.find((value) => normalizeEmail(value) && normalizeEmail(value) !== self) || '';
}

function formatRecipientLine(values: string[], accountEmail: string): string {
  if (!values.length) return accountEmail || 'me';
  return values.map((value) => normalizeEmail(value) === normalizeEmail(accountEmail) ? 'me' : value).join(', ');
}

function initialFor(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '?';
  return trimmed[0].toUpperCase();
}

function threadFallbackMessage(thread: ThreadSummary): GmailMessage {
  return {
    id: `${thread.id}_preview`,
    thread_id: thread.id,
    from_email: thread.from_email || thread.participants?.[0] || '',
    to_emails: thread.to_emails || [],
    subject: thread.subject,
    snippet: thread.snippet,
    body_text: thread.snippet,
    received_at: thread.updated_at,
    is_unread: thread.is_unread,
  };
}

function friendlyNote(value: string): string {
  const compact = value
    .replace(/https?:\/\/\S+/g, 'link')
    .replace(/\s+/g, ' ')
    .replace(/`/g, '')
    .trim();
  if (!compact) return 'Elemento individuato in una conversazione Gmail.';
  if (compact.length <= 180) return compact;
  return `${compact.slice(0, 177).trim()}...`;
}

function returnToShellAfterOAuth() {
  try {
    window.localStorage.setItem('maverick3:base-shell:session', JSON.stringify({ activeAppId: 'gmail-app', isSidebarOpen: false }));
  } catch {
    // If storage is unavailable, falling back to the shell root is still correct.
  }
  if (window.top === window.self) {
    window.location.replace('/');
    return;
  }
  window.history.replaceState({}, document.title, '/apps/gmail-app/');
}
