import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Copy,
  Glasses,
  Laptop,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Smartphone,
  Unplug,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { loadOverview, revokeDevice, startPairing } from './api';
import type { SensesDevice, SensesOverview, SensesPairingSession } from './types';

const APP_EVENTS_WS_PATH = '/api/apps/events/ws';

export function App() {
  const [overview, setOverview] = useState<SensesOverview | null>(null);
  const [pairing, setPairing] = useState<SensesPairingSession | null>(null);
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busyAction, setBusyAction] = useState('');

  const devices = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const items = overview?.devices || [];
    if (!normalized) {
      return items;
    }
    return items.filter((device) => {
      return [
        device.display_name,
        device.device_kind,
        device.platform,
        device.status,
        device.owner_user_id,
      ].some((value) => value.toLowerCase().includes(normalized));
    });
  }, [overview, query]);

  const stats = useMemo(() => {
    const items = overview?.devices || [];
    return {
      total: items.length,
      active: items.filter((device) => device.status === 'active').length,
      revoked: items.filter((device) => device.status === 'revoked').length,
      pending: overview?.pairing_sessions?.length || 0,
    };
  }, [overview]);

  async function refresh(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setBusyAction('refresh');
    }
    try {
      const loaded = await loadOverview();
      setOverview(loaded);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Senses non disponibile.');
    } finally {
      setBusyAction((current) => (current === 'refresh' ? '' : current));
    }
  }

  async function createPairing() {
    setBusyAction('pairing');
    try {
      const created = await startPairing({ deviceKind: 'ios', platform: 'ios' });
      setPairing(created);
      setNotice('Pairing creato.');
      await refresh({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pairing non riuscito.');
    } finally {
      setBusyAction((current) => (current === 'pairing' ? '' : current));
    }
  }

  async function revoke(device: SensesDevice) {
    setBusyAction(device.device_id);
    try {
      await revokeDevice(device.device_id);
      setNotice('Device revocato.');
      await refresh({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Revoca non riuscita.');
    } finally {
      setBusyAction((current) => (current === device.device_id ? '' : current));
    }
  }

  async function copyPairingCode() {
    if (!pairing?.code) {
      return;
    }
    await navigator.clipboard?.writeText(pairing.code);
    setNotice('Codice copiato.');
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timer = window.setTimeout(() => setNotice(''), 2600);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'senses' }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'senses') {
        if (!payload.resource || ['devices', 'pairing', 'settings'].includes(payload.resource)) {
          void refresh({ silent: true });
        }
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  useEffect(() => {
    if (typeof WebSocket === 'undefined') {
      return undefined;
    }
    let closed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer = 0;
    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}${APP_EVENTS_WS_PATH}`);
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data) as { type?: string; owner_app_id?: string; resource?: string };
          if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'senses') {
            if (!payload.resource || ['devices', 'pairing', 'settings'].includes(payload.resource)) {
              void refresh({ silent: true });
            }
          }
        } catch {
          return;
        }
      };
      socket.onclose = () => {
        if (!closed) {
          reconnectTimer = window.setTimeout(connect, 1200);
        }
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  const dependencyStatus = overview?.dependencies.status || 'unknown';
  const loading = !overview && !error;

  return (
    <main className="senses-shell">
      <header className="senses-topbar">
        <div className="senses-title">
          <span className="senses-mark" aria-hidden="true">
            <Activity size={18} />
          </span>
          <div>
            <h1>Senses</h1>
            <p>{overview?.workspace_id || 'default'}</p>
          </div>
        </div>
        <div className="senses-actions">
          <StatusBadge status={dependencyStatus} />
          <button className="icon-button" type="button" onClick={() => void refresh()} title="Aggiorna" aria-label="Aggiorna">
            <RefreshCw size={17} className={busyAction === 'refresh' ? 'spin' : ''} />
          </button>
        </div>
      </header>

      {(notice || error) && (
        <div className={`senses-toast ${error ? 'is-error' : ''}`} role="status">
          {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{error || notice}</span>
          <button type="button" onClick={() => { setError(''); setNotice(''); }} aria-label="Chiudi">
            <X size={15} />
          </button>
        </div>
      )}

      <section className="senses-stats" aria-label="Stato device">
        <Metric label="Device" value={stats.total} />
        <Metric label="Attivi" value={stats.active} tone="good" />
        <Metric label="Revocati" value={stats.revoked} tone="muted" />
        <Metric label="Pairing" value={stats.pending} tone="pending" />
      </section>

      <div className="senses-grid">
        <section className="senses-panel devices-panel">
          <div className="panel-heading">
            <div>
              <h2>Device</h2>
              <p>{overview?.actor.can_manage_workspace_devices ? 'Workspace' : 'Personali'}</p>
            </div>
            <label className="senses-search">
              <Search size={16} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cerca" />
            </label>
          </div>

          {loading ? (
            <DeviceSkeleton />
          ) : devices.length ? (
            <div className="device-list">
              {devices.map((device) => (
                <DeviceRow
                  key={device.device_id}
                  device={device}
                  busy={busyAction === device.device_id}
                  onRevoke={() => void revoke(device)}
                />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <Unplug size={22} />
              <span>Nessun device registrato</span>
            </div>
          )}
        </section>

        <aside className="senses-side">
          <section className="senses-panel pairing-panel">
            <div className="panel-heading compact">
              <div>
                <h2>Pairing</h2>
                <p>{overview?.settings.auth_mode || 'user_session_mvp'}</p>
              </div>
              <button className="primary-button" type="button" onClick={() => void createPairing()} disabled={busyAction === 'pairing'}>
                <Plus size={16} />
                <span>Nuovo</span>
              </button>
            </div>

            {pairing?.code ? (
              <div className="pairing-code-box">
                <span className="code-label">Codice</span>
                <button className="pairing-code" type="button" onClick={() => void copyPairingCode()} title="Copia codice">
                  <span>{pairing.code}</span>
                  <Copy size={16} />
                </button>
                <span className="pairing-expiry">
                  <Clock3 size={14} />
                  {formatDate(pairing.expires_at)}
                </span>
              </div>
            ) : (
              <PendingPairings sessions={overview?.pairing_sessions || []} />
            )}
          </section>

          <section className="senses-panel policy-panel">
            <div className="panel-heading compact">
              <div>
                <h2>Policy</h2>
                <p>{overview?.actor.workspace_role || overview?.actor.platform_role || 'sessione'}</p>
              </div>
              <ShieldCheck size={18} />
            </div>
            <dl className="policy-list">
              <div>
                <dt>Auth</dt>
                <dd>{overview?.settings.auth_mode || 'user_session_mvp'}</dd>
              </div>
              <div>
                <dt>Pairing member</dt>
                <dd>{overview?.settings.allow_member_pairing ? 'on' : 'off'}</dd>
              </div>
              <div>
                <dt>Device ingress</dt>
                <dd>{overview?.settings.device_ingress_enabled ? 'on' : 'off'}</dd>
              </div>
              <div>
                <dt>Storage</dt>
                <dd>{dependencyStatus}</dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>
    </main>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: 'good' | 'muted' | 'pending' }) {
  return (
    <div className={`metric ${tone ? `tone-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DeviceRow({ device, busy, onRevoke }: { device: SensesDevice; busy: boolean; onRevoke: () => void }) {
  const Icon = deviceIcon(device);
  return (
    <article className={`device-row is-${device.status}`}>
      <div className="device-icon" aria-hidden="true">
        <Icon size={19} />
      </div>
      <div className="device-main">
        <div className="device-title">
          <h3>{device.display_name}</h3>
          <span className={`status-pill is-${device.status}`}>{device.status}</span>
        </div>
        <div className="device-meta">
          <span>{device.platform}</span>
          <span>{device.device_kind}</span>
          <span>{formatDate(device.last_seen_at || device.paired_at)}</span>
        </div>
      </div>
      <button
        className="icon-button danger"
        type="button"
        onClick={onRevoke}
        title="Revoca"
        aria-label={`Revoca ${device.display_name}`}
        disabled={!device.can_revoke || busy}
      >
        <X size={16} />
      </button>
    </article>
  );
}

function PendingPairings({ sessions }: { sessions: SensesPairingSession[] }) {
  if (!sessions.length) {
    return (
      <div className="empty-state compact-empty">
        <Clock3 size={20} />
        <span>Nessun pairing aperto</span>
      </div>
    );
  }
  return (
    <div className="pending-list">
      {sessions.slice(0, 3).map((session) => (
        <div className="pending-row" key={session.pairing_id}>
          <span>{session.device_kind || 'ios'}</span>
          <time>{formatDate(session.expires_at)}</time>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const ok = status === 'resolved';
  return (
    <span className={`status-badge ${ok ? 'is-ready' : 'is-blocked'}`}>
      {ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
      {ok ? 'ready' : status}
    </span>
  );
}

function DeviceSkeleton() {
  return (
    <div className="device-list">
      {[0, 1, 2].map((item) => (
        <div className="device-row skeleton" key={item}>
          <span className="device-icon" />
          <span className="skeleton-lines" />
        </div>
      ))}
    </div>
  );
}

function deviceIcon(device: SensesDevice) {
  const text = `${device.device_kind} ${device.platform}`.toLowerCase();
  if (text.includes('glass')) {
    return Glasses;
  }
  if (text.includes('mac') || text.includes('desktop')) {
    return Laptop;
  }
  return Smartphone;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'mai';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('it', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
