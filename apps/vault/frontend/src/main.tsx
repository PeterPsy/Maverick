import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, ClipboardCheck, KeyRound, LockKeyhole, ShieldCheck } from 'lucide-react';
import {
  AuditRecord,
  ProviderStatus,
  SecretGrant,
  SecretGrantTarget,
  SecretRecord,
  getProviderStatus,
  listAudit,
  listGrantTargets,
  listGrants,
  listSecrets
} from './api';
import { AuditView } from './components/AuditView';
import { GrantsView } from './components/GrantsView';
import { ReadinessView } from './components/ReadinessView';
import { SecretsView } from './components/SecretsView';
import { Stat } from './components/VaultShared';
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
      const [secretPayload, grantPayload, auditPayload, targetPayload, providerPayload] = await Promise.all([
        listSecrets(),
        listGrants(),
        listAudit(),
        listGrantTargets(),
        getProviderStatus().catch(() => null)
      ]);
      setSecrets(secretPayload.items);
      setGrants(grantPayload.items);
      setAudit(auditPayload.items);
      setTargets(targetPayload.items);
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
  const activeGrants = useMemo(() => grants.filter((item) => grantStatus(item) === 'active').length, [grants]);
  const riskEvents = useMemo(() => audit.filter((item) => item.status === 'failed' || item.status === 'attempted').length, [audit]);
  const readinessIssues = useMemo(
    () => computeReadinessIssues({ grants, providerStatus, secrets, targets }).length,
    [grants, providerStatus, secrets, targets]
  );
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

  return (
    <main className="vault-shell" aria-busy={busy}>
      <header className="detail-header vault-topbar">
        <div className="detail-title-block vault-heading">
          <h2>Vault</h2>
          <span className="detail-title-separator" aria-hidden="true" />
          <p>Secrets, grants, and audit events for workspace app access.</p>
        </div>
      </header>

      <section className="vault-stats" aria-label="Vault status">
        <Stat active={tab === 'readiness'} icon={<ClipboardCheck size={18} />} label="Readiness issues" onClick={() => applyMetricFilter(null, 'readiness')} value={String(readinessIssues)} />
        <Stat active={metricFilter === 'all-secrets'} icon={<KeyRound size={18} />} label="Total secrets" onClick={() => applyMetricFilter('all-secrets', 'secrets')} value={String(secrets.length)} />
        <Stat active={metricFilter === 'active-secrets'} icon={<ShieldCheck size={18} />} label="Active secrets" onClick={() => applyMetricFilter('active-secrets', 'secrets')} value={String(activeSecrets)} />
        <Stat active={metricFilter === 'active-grants'} icon={<LockKeyhole size={18} />} label="Active grants" onClick={() => applyMetricFilter('active-grants', 'grants')} value={String(activeGrants)} />
        <Stat active={metricFilter === 'review-events'} icon={<AlertTriangle size={18} />} label="Review events" muted={disabledSecrets ? `${disabledSecrets} disabled` : undefined} onClick={() => applyMetricFilter('review-events', 'audit')} value={String(riskEvents)} />
      </section>

      {error ? <div className="vault-error">{error}</div> : null}

      <section className="vault-workspace is-single">
        {tab === 'readiness' ? (
          <ReadinessView
            grants={grants}
            onOpenGrants={() => applyMetricFilter(null, 'grants')}
            providerStatus={providerStatus}
            secrets={secrets}
            targets={targets}
          />
        ) : null}
        {tab === 'secrets' ? (
          <SecretsView
            secrets={filteredSecrets}
            grants={grants}
          />
        ) : null}
        {tab === 'grants' ? <GrantsView grants={filteredGrants} /> : null}
        {tab === 'audit' ? <AuditView audit={filteredAudit} /> : null}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
