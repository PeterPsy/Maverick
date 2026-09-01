import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ClipboardCheck, Search, ShieldCheck } from 'lucide-react';
import {
  AuditRecord,
  ProviderStatus,
  SecretGrant,
  SecretGrantNeed,
  SecretGrantTarget,
  SecretRecord,
  getProviderStatus,
  listAudit,
  listGrantNeeds,
  listGrantTargets,
  listGrants,
  listSecrets
} from './api';
import { AuditView } from './components/AuditView';
import { ConnectionIssuesView } from './components/ConnectionIssuesView';
import { GrantsView } from './components/GrantsView';
import { SecretsView } from './components/SecretsView';
import { Stat } from './components/VaultShared';
import { ConnectionIssue } from './readiness';
import { computeReadinessIssues } from './readiness';
import { ShellNavigatePayload, Tab } from './vaultTypes';
import {
  grantStatus,
  secretMatchesQuery,
  tabFromValue
} from './vaultUtils';
import { VaultMetricFilter, notifyVaultViewStateChanged, readVaultViewState, writeVaultViewState } from './vaultViewState';
import './styles.css';

function App() {
  const initialViewState = readVaultViewState();
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [grants, setGrants] = useState<SecretGrant[]>([]);
  const [targets, setTargets] = useState<SecretGrantTarget[]>([]);
  const [grantNeeds, setGrantNeeds] = useState<SecretGrantNeed[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [tab, setTab] = useState<Tab>(() => tabFromValue(new URLSearchParams(window.location.search).get('tab')) || initialViewState.tab);
  const [metricFilter, setMetricFilter] = useState<VaultMetricFilter>(() => initialViewState.metricFilter);
  const [query, setQuery] = useState(() => initialViewState.query);
  const [selectedSecretId, setSelectedSecretId] = useState(() => initialViewState.selectedSecretId);
  const [credentialPanel, setCredentialPanel] = useState(() => initialViewState.credentialPanel);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function refresh() {
    setBusy(true);
    setError('');
    try {
      const [secretPayload, grantPayload, auditPayload, targetPayload, needPayload, providerPayload] = await Promise.all([
        listSecrets(),
        listGrants(),
        listAudit(),
        listGrantTargets(),
        listGrantNeeds().catch(() => ({ items: [] as SecretGrantNeed[] })),
        getProviderStatus().catch(() => null)
      ]);
      setSecrets(secretPayload.items);
      setGrants(grantPayload.items);
      setAudit(auditPayload.items);
      setTargets(targetPayload.items);
      setGrantNeeds(needPayload.items.length ? needPayload.items : targetPayload.needs || []);
      setProviderStatus(providerPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed.');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'vault' }, "*");
  }, []);

  useEffect(() => {
    writeVaultViewState({ credentialPanel, metricFilter, query, selectedSecretId, tab });
    notifyVaultViewStateChanged();
  }, [credentialPanel, metricFilter, query, selectedSecretId, tab]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as ShellNavigatePayload & { owner_app_id?: string; resource?: string };
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'vault' && payload.resource === 'state') {
        void refresh();
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'vault' && payload.resource === 'view-state') {
        const nextState = readVaultViewState();
        setCredentialPanel(nextState.credentialPanel);
        setMetricFilter(nextState.metricFilter);
        setQuery(nextState.query);
        setSelectedSecretId(nextState.selectedSecretId);
        setTab(nextState.tab);
        return;
      }
      if (payload.type !== 'maverick.app.navigate' || (payload.app_id && payload.app_id !== 'vault')) {
        return;
      }
      const nextTab = tabFromValue(payload.params?.tab);
      if (nextTab) {
        setMetricFilter(null);
        setTab(nextTab);
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  const activeSecrets = useMemo(() => secrets.filter((item) => item.status === 'active'), [secrets]);
  const filteredActiveSecrets = useMemo(() => activeSecrets.filter((item) => secretMatchesQuery(item, query)), [activeSecrets, query]);
  const connectionIssues = useMemo<ConnectionIssue[]>(
    () => computeReadinessIssues({ grants, grantNeeds, providerStatus, secrets, targets }),
    [grants, grantNeeds, providerStatus, secrets, targets]
  );
  const filteredGrants = useMemo(
    () => grants
      .filter((grant) => metricFilter !== 'active-grants' || grantStatus(grant) === 'active'),
    [grants, metricFilter]
  );
  const filteredAudit = useMemo(
    () => audit
      .filter((item) => metricFilter !== 'review-events' || item.status === 'failed' || item.status === 'attempted'),
    [audit, metricFilter]
  );
  const filteredConnectionIssues = useMemo(
    () => connectionIssues.filter((issue) => issueMatchesQuery(issue, query)),
    [connectionIssues, query]
  );

  function openTab(nextTab: Tab) {
    setMetricFilter(null);
    setTab(nextTab);
  }

  function updateQuery(nextQuery: string) {
    setQuery(nextQuery);
    const currentState = readVaultViewState();
    writeVaultViewState({ ...currentState, query: nextQuery });
    notifyVaultViewStateChanged();
  }

  function selectCredential(secretId: string) {
    setMetricFilter(null);
    setSelectedSecretId(secretId);
    setCredentialPanel('edit');
    setTab('credentials');
    const currentState = readVaultViewState();
    writeVaultViewState({ ...currentState, credentialPanel: 'edit', metricFilter: null, selectedSecretId: secretId, tab: 'credentials' });
    notifyVaultViewStateChanged();
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.open' }, "*");
  }

  return (
    <main className="vault-shell" aria-busy={busy}>
      <header className="detail-header vault-topbar">
        <div className="detail-title-block vault-heading">
          <h2>Vault</h2>
          <span className="detail-title-separator" aria-hidden="true" />
          <p>Securely save credentials so agents can connect workspace apps.</p>
        </div>
      </header>

      <section className="vault-workspace-controls" aria-label="Vault controls">
        <div className="vault-stats" aria-label="Vault views">
          <Stat active={tab === 'credentials'} icon={<ShieldCheck size={17} />} label="Active Credential" onClick={() => openTab('credentials')} value={String(activeSecrets.length)} />
          <Stat active={tab === 'issues'} icon={<ClipboardCheck size={17} />} label="Connection Issues" onClick={() => openTab('issues')} value={String(connectionIssues.length)} />
        </div>
        <label className="vault-search">
          <Search size={17} aria-hidden="true" />
          <input
            aria-label="Search Vault"
            onChange={(event) => updateQuery(event.currentTarget.value)}
            placeholder="Search Vault"
            value={query}
          />
        </label>
      </section>

      {error ? <div className="vault-error">{error}</div> : null}

      <section className="vault-workspace is-single">
        {tab === 'issues' ? (
          <ConnectionIssuesView issues={filteredConnectionIssues} />
        ) : null}
        {tab === 'credentials' ? (
          <SecretsView
            secrets={filteredActiveSecrets}
            grants={grants}
            issues={filteredConnectionIssues}
            onSelectSecret={selectCredential}
            selectedSecretId={selectedSecretId}
          />
        ) : null}
        {tab === 'advanced' ? (
          <div className="vault-advanced-stack">
            <GrantsView grants={filteredGrants} />
            <AuditView audit={filteredAudit} />
          </div>
        ) : null}
      </section>
    </main>
  );
}

function issueMatchesQuery(issue: ConnectionIssue, query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return [
    issue.title,
    issue.summary,
    issue.appDisplayName,
    issue.credentialLabel,
    issue.recommendedAction,
    issue.status,
    issue.technicalDetails
  ].join(' ').toLowerCase().includes(needle);
}

createRoot(document.getElementById('root')!).render(<App />);
