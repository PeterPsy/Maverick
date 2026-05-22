import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ClipboardCheck, Clock3, KeyRound, LockKeyhole, Plus, Search, ShieldCheck } from 'lucide-react';
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
import { appSecretTarget, grantCoversSecretTarget, isCurrentActiveGrant, secretConsumerTargets } from '../../readiness';
import { GRANT_ACTIONS, GRANT_TARGET_MODES, GrantTargetMode, Tab } from '../../vaultTypes';
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
  const [grantLogicalName, setGrantLogicalName] = useState('');
  const [grantTargetMode, setGrantTargetMode] = useState<GrantTargetMode>('app_backend_all');
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
  const selectedGrantLogicalNames = useMemo(
    () => selectedGrantApp ? selectedGrantApp.logical_names.filter((logicalName) => hasUncoveredConsumers(selectedGrantApp, logicalName, grants)) : [],
    [grants, selectedGrantApp]
  );
  const selectedLogicalConsumer = selectedGrantApp?.consumers?.[grantLogicalName.toLowerCase()];
  const selectedBackendAvailable = Boolean(selectedGrantApp && grantLogicalName && secretConsumerTargets(selectedGrantApp, grantLogicalName).backend.some((target) => !grantTargetCovered(grants, grantAppId, grantLogicalName, target)));
  const selectedCliCommands = useMemo(
    () => (selectedLogicalConsumer?.cli_commands || []).filter((command) => !grantTargetCovered(grants, grantAppId, grantLogicalName, appSecretTarget(`cli/${command}`))),
    [grantAppId, grantLogicalName, grants, selectedLogicalConsumer]
  );
  const selectedMcpTools = useMemo(
    () => (selectedLogicalConsumer?.mcp_tools || []).filter((tool) => !grantTargetCovered(grants, grantAppId, grantLogicalName, appSecretTarget(`mcp/${tool}`))),
    [grantAppId, grantLogicalName, grants, selectedLogicalConsumer]
  );
  const activeLogicalGrantExists = useMemo(
    () => grants.some((item) => grantBlocksLogicalNameSelection(item, grantAppId, grantLogicalName)),
    [grantAppId, grantLogicalName, grants]
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
      setGrantLogicalName('');
    }
  }, [grantAppId, grantableApps]);

  useEffect(() => {
    if (grantLogicalName && !selectedGrantLogicalNames.includes(grantLogicalName)) {
      setGrantLogicalName('');
    }
  }, [grantLogicalName, selectedGrantLogicalNames]);

  useEffect(() => {
    const targetModeUnavailable = (grantTargetMode === 'app_backend_all' && activeLogicalGrantExists)
      || (grantTargetMode === 'app_cli' && !selectedCliCommands.length)
      || (grantTargetMode === 'app_mcp' && !selectedMcpTools.length)
      || (grantTargetMode === 'app_backend' && !selectedBackendAvailable);
    if (targetModeUnavailable) {
      setGrantTargetMode(
        !grantLogicalName || !activeLogicalGrantExists ? 'app_backend_all'
          : selectedBackendAvailable ? 'app_backend'
            : selectedCliCommands.length ? 'app_cli'
              : selectedMcpTools.length ? 'app_mcp'
                : 'custom'
      );
    }
  }, [activeLogicalGrantExists, grantLogicalName, grantTargetMode, selectedBackendAvailable, selectedCliCommands.length, selectedMcpTools.length]);

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
      setGrantLogicalName('');
      setGrantTargetMode('app_backend_all');
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
          <button className={tab === 'readiness' ? 'is-active' : ''} onClick={() => openTab('readiness')} type="button">
            <span className="vault-sidebar-row__icon" aria-hidden="true"><ClipboardCheck size={17} /></span>
            <span className="vault-sidebar-row__copy"><strong>Ready</strong><small>Checks</small></span>
          </button>
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
            <select
              name="app_id"
              onChange={(event) => {
                setGrantAppId(event.currentTarget.value);
                setGrantLogicalName('');
                setGrantTargetMode('app_backend_all');
              }}
              required
              value={grantAppId}
            >
              <option value="">App with declared secret</option>
              {grantableApps.map((app) => (
                <option key={app.app_id} value={app.app_id}>{app.name || app.app_id}</option>
              ))}
            </select>
            <select
              name="logical_name"
              onChange={(event) => {
                setGrantLogicalName(event.currentTarget.value);
                setGrantTargetMode('app_backend_all');
              }}
              required
              disabled={!selectedGrantLogicalNames.length}
              value={grantLogicalName}
            >
              <option value="">Declared logical name</option>
              {selectedGrantLogicalNames.map((logicalName) => (
                <option key={logicalName} value={logicalName}>{logicalName}</option>
              ))}
            </select>
            {!grantableApps.length ? <p className="vault-sidebar-warning">No enabled app declares secret access.</p> : null}
            {selectedGrantApp && !selectedGrantLogicalNames.length ? <p className="vault-sidebar-warning">All declared secret consumers for this app already have current grants.</p> : null}
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
            <select name="target_mode" onChange={(event) => setGrantTargetMode(event.currentTarget.value as GrantTargetMode)} value={grantTargetMode}>
              {GRANT_TARGET_MODES.map((mode) => (
                <option
                  disabled={!grantLogicalName
                    || (mode.value === 'app_backend_all' && activeLogicalGrantExists)
                    || (mode.value === 'app_backend' && !selectedBackendAvailable)
                    || (mode.value === 'app_cli' && !selectedCliCommands.length)
                    || (mode.value === 'app_mcp' && !selectedMcpTools.length)}
                  key={mode.value}
                  value={mode.value}
                >
                  {mode.label}
                </option>
              ))}
            </select>
            {grantTargetMode === 'app_cli' ? (
              <select name="target_cli_command" required>
                <option value="">CLI command</option>
                {selectedCliCommands.map((command) => (
                  <option key={command} value={command}>{command}</option>
                ))}
              </select>
            ) : null}
            {grantTargetMode === 'app_mcp' ? (
              <select name="target_mcp_tool" required>
                <option value="">MCP tool</option>
                {selectedMcpTools.map((tool) => (
                  <option key={tool} value={tool}>{tool}</option>
                ))}
              </select>
            ) : null}
            {grantTargetMode === 'custom' ? (
              <input name="target_custom" placeholder="maverick://app.backend/backend" required />
            ) : null}
            <input name="expires_at" type="datetime-local" />
            <textarea name="reason" placeholder="Reason" rows={3} />
          </form>
        ) : null}

        {tab === 'readiness' ? (
          <div className="vault-sidebar-status">
            Readiness runs in the main Vault view and flags missing app grants, blocked grants, disabled linked secrets, and provider credential state.
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

function isMobileLayoutViewport() {
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia('(max-width: 979px)').matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 979px)').matches;
  }
}

function hasUncoveredConsumers(app: SecretGrantTarget, logicalName: string, grants: SecretGrant[]) {
  return secretConsumerTargets(app, logicalName).all.some((target) => !grantTargetCovered(grants, app.app_id, logicalName, target));
}

function grantTargetCovered(grants: SecretGrant[], appId: string, logicalName: string, target: string) {
  return grants.some((grant) => isCurrentActiveGrant(grant) && grantCoversSecretTarget(grant, appId, logicalName, target));
}

function grantBlocksLogicalNameSelection(grant: SecretGrant, appId: string, logicalName: string, now = Date.now()) {
  if (
    grant.app_id !== appId
    || grant.logical_name.toLowerCase() !== logicalName.toLowerCase()
    || grant.status !== 'active'
    || !grant.actions.map((action) => action.toLowerCase()).includes('app.backend')
  ) {
    return false;
  }
  if (!grant.expires_at) {
    return true;
  }
  const expiresAt = Date.parse(grant.expires_at);
  return Number.isNaN(expiresAt) || expiresAt > now;
}

createRoot(document.getElementById('vault-sidebar-root') as HTMLElement).render(<VaultSidebarWidget />);
