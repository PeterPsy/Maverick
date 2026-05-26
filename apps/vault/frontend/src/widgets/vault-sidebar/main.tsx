import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, ClipboardCheck, KeyRound, RotateCcw, Search, ShieldCheck, Upload } from 'lucide-react';
import {
  AuditRecord,
  ProviderStatus,
  SecretGrant,
  SecretGrantNeed,
  SecretGrantTarget,
  SecretRecord,
  createSecret,
  getProviderStatus,
  listAudit,
  listGrantNeeds,
  listGrantTargets,
  listGrants,
  listSecrets,
  rotateSecret
} from '../../api';
import { SecureSecretInput } from '../../components/SecureSecretInput';
import { ConnectionIssue, computeReadinessIssues } from '../../readiness';
import { Tab } from '../../vaultTypes';
import { secretMatchesQuery } from '../../vaultUtils';
import { notifyVaultDataChanged, notifyVaultViewStateChanged, readVaultActionRequest, readVaultViewState, writeVaultViewState } from '../../vaultViewState';
import '../widget-styles.css';

function VaultSidebarWidget() {
  const appId = currentVaultAppId();
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [grants, setGrants] = useState<SecretGrant[]>([]);
  const [targets, setTargets] = useState<SecretGrantTarget[]>([]);
  const [grantNeeds, setGrantNeeds] = useState<SecretGrantNeed[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [query, setQuery] = useState(() => readVaultViewState().query);
  const [tab, setTab] = useState<Tab>(() => readVaultViewState().tab);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const lastActionRequestId = useRef('');
  const credentialFormRef = useRef<HTMLFormElement | null>(null);
  const rotateFormRef = useRef<HTMLFormElement | null>(null);

  const activeSecrets = useMemo(() => secrets.filter((item) => item.status === 'active'), [secrets]);
  const filteredSecrets = useMemo(() => secrets.filter((item) => secretMatchesQuery(item, query)), [query, secrets]);
  const issues = useMemo(() => computeReadinessIssues({ grants, grantNeeds, providerStatus, secrets, targets }), [grants, grantNeeds, providerStatus, secrets, targets]);
  const isAdvancedMode = useMemo(() => isAdvancedModeEnabled(), []);

  async function refresh() {
    try {
      const [secretPayload, grantPayload, targetPayload, needPayload, auditPayload, providerPayload] = await Promise.all([
        listSecrets(),
        listGrants(),
        listGrantTargets(),
        listGrantNeeds().catch(() => ({ items: [] as SecretGrantNeed[] })),
        listAudit(),
        getProviderStatus().catch(() => null)
      ]);
      setSecrets(secretPayload.items);
      setGrants(grantPayload.items);
      setTargets(targetPayload.items);
      setGrantNeeds(needPayload.items.length ? needPayload.items : targetPayload.needs || []);
      setAudit(auditPayload.items);
      setProviderStatus(providerPayload);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Vault.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.type === 'maverick.widget.context-changed' || (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === appId)) {
        if (payload.resource === 'view-state') {
          const nextState = readVaultViewState();
          setQuery(nextState.query);
          setTab(advancedAwareTab(nextState.tab, isAdvancedMode));
        }
        if (payload.resource === 'action-request') {
          runRequestedAction();
        }
        void refresh();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId, isAdvancedMode]);

  function runRequestedAction() {
    const request = readVaultActionRequest();
    if (!request || request.id === lastActionRequestId.current) {
      return;
    }
    lastActionRequestId.current = request.id;
    if (request.action === 'submit-credential') {
      openTab('credentials');
      window.setTimeout(() => credentialFormRef.current?.requestSubmit(), 0);
    }
    if (request.action === 'rotate-credential') {
      openTab('credentials');
      window.setTimeout(() => rotateFormRef.current?.requestSubmit(), 0);
    }
    if (request.action === 'import-credentials') {
      openTab('import');
    }
  }

  function openTab(nextTab: Tab) {
    const allowedTab = advancedAwareTab(nextTab, isAdvancedMode);
    setTab(allowedTab);
    writeVaultViewState({ metricFilter: null, query, tab: allowedTab });
    notifyVaultViewStateChanged();
    window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: appId, params: { tab: allowedTab } }, window.location.origin);
    if (isMobileLayoutViewport()) {
      window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
    }
  }

  function updateQuery(nextQuery: string) {
    setQuery(nextQuery);
    writeVaultViewState({ metricFilter: null, query: nextQuery, tab });
    notifyVaultViewStateChanged();
  }

  async function submit(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
      await refresh();
      notifyVaultDataChanged();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Vault request failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const rawValue = String(form.get('raw_value') || '');
    formElement.reset();
    await submit(async () => {
      await createSecret({
        label: String(form.get('label') || ''),
        alias: String(form.get('alias') || '') || undefined,
        description: String(form.get('description') || '') || undefined,
        raw_value: rawValue,
        kind: String(form.get('kind') || 'generic')
      });
    });
  }

  async function handleRotateCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const secretId = String(form.get('secret_id') || '');
    const rawValue = String(form.get('raw_value') || '');
    formElement.reset();
    await submit(async () => {
      await rotateSecret(secretId, rawValue);
    });
  }

  function askAgentToFix(issue: ConnectionIssue) {
    window.parent?.postMessage(
      {
        type: 'maverick.widget.open-app',
        app_id: 'chat',
        params: {
          prompt: `Help fix this Vault credential issue: ${issue.title}`
        }
      },
      window.location.origin
    );
  }

  return (
    <main className="vault-sidebar-widget" aria-busy={busy}>
      <div className="vault-sidebar-search-frame">
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search Vault"
          className="vault-sidebar-search"
          onChange={(event) => updateQuery(event.currentTarget.value)}
          placeholder="Search Vault"
          value={query}
        />
      </div>

      <section className="vault-sidebar-list">
        <nav className="vault-sidebar-nav" aria-label="Vault sections">
          <button className={tab === 'credentials' ? 'is-active' : ''} onClick={() => openTab('credentials')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><KeyRound size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Credential Inbox</strong><small>{filteredSecrets.length} records</small></span>
          </button>
          <button className={tab === 'issues' ? 'is-active' : ''} onClick={() => openTab('issues')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><ClipboardCheck size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Connection Issues</strong><small>{issues.length} open</small></span>
          </button>
          <button className={tab === 'import' ? 'is-active' : ''} onClick={() => openTab('import')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><Upload size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Import</strong><small>CSV</small></span>
          </button>
          {isAdvancedMode ? (
            <button className={tab === 'advanced' ? 'is-active' : ''} onClick={() => openTab('advanced')} type="button">
              <span className="vault-sidebar-row__icon" aria-hidden="true"><ShieldCheck size={17} /></span>
              <span className="vault-sidebar-row__copy"><strong>Advanced</strong><small>{grants.length} grant records · {audit.length} audit events</small></span>
            </button>
          ) : null}
        </nav>

        {tab === 'credentials' ? (
          <div className="vault-sidebar-form-stack">
            <form className="vault-sidebar-form" onSubmit={handleCreateCredential} ref={credentialFormRef}>
              <p className="vault-sidebar-section-title"><KeyRound size={14} aria-hidden="true" />Add credential</p>
              <input name="label" placeholder="Label" required />
              <input name="alias" placeholder="alias-name" />
              <select name="kind" defaultValue="generic">
                <option value="generic">Generic</option>
                <option value="password">Password</option>
                <option value="api_key">API key</option>
                <option value="oauth_token">OAuth token</option>
                <option value="private_key">Private key</option>
              </select>
              <textarea name="description" placeholder="Description" rows={3} />
              <SecureSecretInput label="Credential value" />
            </form>
            <form className="vault-sidebar-form" onSubmit={handleRotateCredential} ref={rotateFormRef}>
              <p className="vault-sidebar-section-title"><RotateCcw size={14} aria-hidden="true" />Rotate credential</p>
              <select name="secret_id" required>
                <option value="">Credential</option>
                {activeSecrets.map((secret) => (
                  <option key={secret.secret_id} value={secret.secret_id}>{secret.label}</option>
                ))}
              </select>
              <SecureSecretInput label="New credential value" />
            </form>
          </div>
        ) : null}

        {tab === 'issues' ? (
          <div className="vault-sidebar-issues">
            {issues.length ? issues.slice(0, 8).map((issue) => (
              <article className="vault-sidebar-issue" key={issue.id}>
                <span className="vault-sidebar-issue__icon" aria-hidden="true"><AlertTriangle size={15} /></span>
                <div>
                  <strong>{issue.title}</strong>
                  <small>{issue.appDisplayName} · {issue.recommendedAction}</small>
                </div>
                <div className="vault-sidebar-issue__actions">
                  <button onClick={() => openTab('credentials')} type="button">Add value</button>
                  <button onClick={() => askAgentToFix(issue)} type="button">Ask agent to fix</button>
                  <button onClick={() => openTab('issues')} type="button">Review fix</button>
                </div>
              </article>
            )) : (
              <div className="vault-sidebar-status">No credential issues need attention.</div>
            )}
          </div>
        ) : null}

        {tab === 'import' ? (
          <div className="vault-sidebar-status">
            Use the CSV import control in the sidebar footer to add credentials in bulk.
          </div>
        ) : null}

        {tab === 'advanced' && isAdvancedMode ? (
          <div className="vault-sidebar-status">
            Grant and audit review remain available in the main Vault view for admin and developer diagnostics.
          </div>
        ) : null}

        {error ? <p className="vault-sidebar-status">{error}</p> : null}
        {loading && !error ? <p className="vault-sidebar-status">Loading Vault metadata...</p> : null}
      </section>
    </main>
  );
}

function currentVaultAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return 'vault';
  }
  try {
    return decodeURIComponent(match[1]) || 'vault';
  } catch {
    return match[1] || 'vault';
  }
}

function isAdvancedModeEnabled() {
  if (typeof window === 'undefined') {
    return false;
  }
  const params = new URLSearchParams(window.location.search);
  return params.get('advanced') === '1' || window.localStorage.getItem('maverick.developerMode') === 'true';
}

function advancedAwareTab(tab: Tab, advancedEnabled: boolean): Tab {
  return tab === 'advanced' && !advancedEnabled ? 'credentials' : tab;
}

function isMobileLayoutViewport() {
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia('(max-width: 979px)').matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 979px)').matches;
  }
}

createRoot(document.getElementById('vault-sidebar-root') as HTMLElement).render(<VaultSidebarWidget />);
