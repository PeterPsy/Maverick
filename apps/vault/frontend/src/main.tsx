import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ClipboardCheck, KeyRound, ShieldCheck, Upload } from 'lucide-react';
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
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'vault' }, window.location.origin);
  }, []);

  useEffect(() => {
    writeVaultViewState({ metricFilter, query: readVaultViewState().query, tab });
    notifyVaultViewStateChanged();
  }, [metricFilter, tab]);

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
        setMetricFilter(nextState.metricFilter);
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

  const activeSecrets = useMemo(() => secrets.filter((item) => item.status === 'active').length, [secrets]);
  const disabledSecrets = useMemo(() => secrets.filter((item) => item.status === 'disabled').length, [secrets]);
  const connectionIssues = useMemo<ConnectionIssue[]>(
    () => computeReadinessIssues({ grants, grantNeeds, providerStatus, secrets, targets }),
    [grants, grantNeeds, providerStatus, secrets, targets]
  );
  const providerHealth = providerStatus?.blocked_reason ? 'Needs review' : 'Ready';
  const filteredSecrets = useMemo(
    () => secrets
      .filter((secret) => metricFilter !== 'active-secrets' || secret.status === 'active'),
    [metricFilter, secrets]
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

  function applyMetricFilter(nextFilter: VaultMetricFilter, nextTab: Tab) {
    setTab(nextTab);
    setMetricFilter((current) => (current === nextFilter ? null : nextFilter));
  }

  function openTab(nextTab: Tab) {
    setMetricFilter(null);
    setTab(nextTab);
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
    <main className="vault-shell" aria-busy={busy}>
      <header className="detail-header vault-topbar">
        <div className="detail-title-block vault-heading">
          <h2>Credential Inbox</h2>
          <span className="detail-title-separator" aria-hidden="true" />
          <p>Saved credentials and connection issues for workspace app access.</p>
        </div>
      </header>

      <section className="vault-stats" aria-label="Vault status">
        <Stat active={metricFilter === 'all-secrets'} icon={<KeyRound size={18} />} label="Credential Inbox" onClick={() => applyMetricFilter('all-secrets', 'credentials')} value={String(secrets.length)} />
        <Stat active={metricFilter === 'active-secrets'} icon={<ShieldCheck size={18} />} label="Active credentials" onClick={() => applyMetricFilter('active-secrets', 'credentials')} value={String(activeSecrets)} />
        <Stat active={tab === 'issues'} icon={<ClipboardCheck size={18} />} label="Connection Issues" muted={disabledSecrets ? `${disabledSecrets} disabled` : undefined} onClick={() => applyMetricFilter(null, 'issues')} value={String(connectionIssues.length)} />
        <Stat icon={<ShieldCheck size={18} />} label="Provider health" onClick={() => openTab(providerStatus?.blocked_reason ? 'issues' : 'credentials')} value={providerHealth} />
      </section>

      {error ? <div className="vault-error">{error}</div> : null}

      <section className="vault-workspace is-single">
        {tab === 'issues' ? (
          <ConnectionIssuesView
            issues={connectionIssues}
            onAddValue={() => openTab('credentials')}
            onAskAgent={askAgentToFix}
            onReviewFix={() => openTab('issues')}
          />
        ) : null}
        {tab === 'credentials' ? (
          <SecretsView
            secrets={filteredSecrets}
            grants={grants}
            issues={connectionIssues}
          />
        ) : null}
        {tab === 'import' ? (
          <section className="vault-import-view">
            <div className="vault-panel-header">
              <div>
                <h2><Upload size={17} />Import</h2>
                <p>Use the sidebar CSV import control to create credentials in bulk without composing app grants.</p>
              </div>
            </div>
          </section>
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

createRoot(document.getElementById('root')!).render(<App />);
