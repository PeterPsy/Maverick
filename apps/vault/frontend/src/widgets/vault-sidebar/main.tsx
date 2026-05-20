import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Clock3, KeyRound, LockKeyhole, Plus, Search, ShieldCheck } from 'lucide-react';
import {
  AuditRecord,
  SecretGrantTarget,
  SecretGrant,
  SecretRecord,
  createGrant,
  createSecret,
  listAudit,
  listGrantTargets,
  listGrants,
  listSecrets
} from '../../api';
import { GRANT_ACTIONS, Tab } from '../../vaultTypes';
import {
  auditMatchesQuery,
  buildTargetPatterns,
  grantMatchesQuery,
  grantStatus,
  secretMatchesQuery,
  toApiExpiry
} from '../../vaultUtils';
import { notifyVaultDataChanged, notifyVaultViewStateChanged, readVaultActionRequest, readVaultViewState, writeVaultViewState } from '../../vaultViewState';
import '../widget-styles.css';

function VaultSidebarWidget() {
  const appId = currentVaultAppId();
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [grants, setGrants] = useState<SecretGrant[]>([]);
  const [apps, setApps] = useState<SecretGrantTarget[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [query, setQuery] = useState(() => readVaultViewState().query);
  const [tab, setTab] = useState<Tab>(() => readVaultViewState().tab);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [grantAppId, setGrantAppId] = useState('');
  const lastActionRequestId = useRef('');
  const secretFormRef = useRef<HTMLFormElement | null>(null);
  const grantFormRef = useRef<HTMLFormElement | null>(null);

  const filteredSecrets = useMemo(() => secrets.filter((item) => secretMatchesQuery(item, query)), [query, secrets]);
  const filteredGrants = useMemo(() => grants.filter((item) => grantMatchesQuery(item, query)), [grants, query]);
  const filteredAudit = useMemo(() => audit.filter((item) => auditMatchesQuery(item, query)), [audit, query]);
  const activeGrants = useMemo(() => grants.filter((item) => grantStatus(item) === 'active').length, [grants]);
  const grantableApps = useMemo(() => apps
    .filter((item) => item.status === 'enabled' && item.logical_names.length > 0)
    .sort((left, right) => (left.name || left.app_id).localeCompare(right.name || right.app_id)), [apps]);
  const selectedGrantApp = useMemo(() => grantableApps.find((item) => item.app_id === grantAppId), [grantAppId, grantableApps]);
  const activeGrantedLogicalNames = useMemo(() => new Set(
    grants
      .filter((item) => grantBlocksLogicalNameSelection(item, grantAppId))
      .map((item) => item.logical_name.toLowerCase())
  ), [grantAppId, grants]);
  const selectedGrantLogicalNames = useMemo(
    () => (selectedGrantApp?.logical_names || []).filter((logicalName) => !activeGrantedLogicalNames.has(logicalName.toLowerCase())),
    [activeGrantedLogicalNames, selectedGrantApp]
  );

  async function refresh() {
    try {
      const [secretPayload, grantPayload, auditPayload, targetPayload] = await Promise.all([listSecrets(), listGrants(), listAudit(), listGrantTargets()]);
      setSecrets(secretPayload.items);
      setGrants(grantPayload.items);
      setAudit(auditPayload.items);
      setApps(targetPayload.items);
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
    if (grantAppId && !grantableApps.some((item) => item.app_id === grantAppId)) {
      setGrantAppId('');
    }
  }, [grantAppId, grantableApps]);

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
          setTab(nextState.tab);
        }
        if (payload.resource === 'action-request') {
          runRequestedAction();
        }
        void refresh();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  function runRequestedAction() {
    const request = readVaultActionRequest();
    if (!request || request.id === lastActionRequestId.current) {
      return;
    }
    lastActionRequestId.current = request.id;
    if (request.action === 'submit-secret') {
      setTab('secrets');
      window.setTimeout(() => secretFormRef.current?.requestSubmit(), 0);
    }
    if (request.action === 'submit-grant') {
      setTab('grants');
      window.setTimeout(() => grantFormRef.current?.requestSubmit(), 0);
    }
  }

  function openTab(tab: Tab) {
    setTab(tab);
    writeVaultViewState({ metricFilter: null, query, tab });
    notifyVaultViewStateChanged();
    window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: appId, params: { tab } }, window.location.origin);
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

  async function handleCreateSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await submit(async () => {
      await createSecret({
        label: String(form.get('label') || ''),
        alias: String(form.get('alias') || '') || undefined,
        description: String(form.get('description') || '') || undefined,
        raw_value: String(form.get('raw_value') || ''),
        kind: String(form.get('kind') || 'generic')
      });
      event.currentTarget.reset();
    });
  }

  async function handleCreateGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await submit(async () => {
      await createGrant({
        secret_id: String(form.get('secret_id') || ''),
        app_id: String(form.get('app_id') || ''),
        logical_name: String(form.get('logical_name') || ''),
        actions: form.getAll('actions').map(String).filter(Boolean),
        target_patterns: buildTargetPatterns(form),
        expires_at: toApiExpiry(String(form.get('expires_at') || '')) || undefined,
        reason: String(form.get('reason') || '') || undefined
      });
      event.currentTarget.reset();
      setGrantAppId('');
    });
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
          <button className={tab === 'secrets' ? 'is-active' : ''} onClick={() => openTab('secrets')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><KeyRound size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Secrets</strong><small>{filteredSecrets.length} records</small></span>
          </button>
          <button className={tab === 'grants' ? 'is-active' : ''} onClick={() => openTab('grants')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><LockKeyhole size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Grants</strong><small>{filteredGrants.length} records · {activeGrants} active</small></span>
          </button>
          <button className={tab === 'audit' ? 'is-active' : ''} onClick={() => openTab('audit')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><Clock3 size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Audit</strong><small>{filteredAudit.length} events</small></span>
          </button>
        </nav>

        {tab === 'secrets' ? (
          <form className="vault-sidebar-form" onSubmit={handleCreateSecret} ref={secretFormRef}>
            <p className="vault-sidebar-section-title"><Plus size={14} aria-hidden="true" />New secret</p>
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
            <input name="raw_value" placeholder="Value" type="password" required autoComplete="new-password" />
          </form>
        ) : null}

        {tab === 'grants' ? (
          <form className="vault-sidebar-form" onSubmit={handleCreateGrant} ref={grantFormRef}>
            <p className="vault-sidebar-section-title"><ShieldCheck size={14} aria-hidden="true" />New grant</p>
            <select name="secret_id" required>
              <option value="">Secret</option>
              {secrets.filter((item) => item.status === 'active').map((secret) => (
                <option key={secret.secret_id} value={secret.secret_id}>{secret.label}</option>
              ))}
            </select>
            <select name="app_id" onChange={(event) => setGrantAppId(event.currentTarget.value)} required value={grantAppId}>
              <option value="">App with declared secret</option>
              {grantableApps.map((app) => (
                <option key={app.app_id} value={app.app_id}>{app.name || app.app_id}</option>
              ))}
            </select>
            <select name="logical_name" required disabled={!selectedGrantLogicalNames.length}>
              <option value="">Declared logical name</option>
              {selectedGrantLogicalNames.map((logicalName) => (
                <option key={logicalName} value={logicalName}>{logicalName}</option>
              ))}
            </select>
            {!grantableApps.length ? <p className="vault-sidebar-warning">No enabled app declares secret access.</p> : null}
            {selectedGrantApp && !selectedGrantLogicalNames.length ? <p className="vault-sidebar-warning">All declared logical names for this app already have active grants.</p> : null}
            <fieldset className="vault-sidebar-fieldset">
              <legend>Actions</legend>
              {GRANT_ACTIONS.map((action) => (
                <label key={action.value}>
                  <input
                    type="radio"
                    name="actions"
                    value={action.value}
                    defaultChecked
                    readOnly
                  />
                  <span>{action.label}</span>
                </label>
              ))}
            </fieldset>
            <input name="target_mode" type="hidden" value="app_backend" />
            <input name="expires_at" type="datetime-local" />
            <textarea name="reason" placeholder="Reason" rows={3} />
          </form>
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

function isMobileLayoutViewport() {
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia('(max-width: 979px)').matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 979px)').matches;
  }
}

function grantBlocksLogicalNameSelection(grant: SecretGrant, appId: string, now = Date.now()) {
  if (grant.app_id !== appId || grant.status !== 'active') {
    return false;
  }
  if (!grant.expires_at) {
    return true;
  }
  const expiresAt = Date.parse(grant.expires_at);
  return Number.isNaN(expiresAt) || expiresAt > now;
}

createRoot(document.getElementById('vault-sidebar-root') as HTMLElement).render(<VaultSidebarWidget />);
