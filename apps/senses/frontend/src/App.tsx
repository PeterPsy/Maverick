import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Clock3,
  Copy,
  Database,
  Glasses,
  HardDrive,
  KeyRound,
  Laptop,
  Link2,
  ListChecks,
  LogIn,
  MessageSquare,
  Mic,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  Route,
  Search,
  Send,
  Settings as SettingsIcon,
  ShieldCheck,
  SlidersHorizontal,
  Smartphone,
  Unplug,
  Wrench,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadOverview, loadViewFilter, resetRoutingSession, revokeDevice, setViewFilter, startPairing, updateSettings } from './api';
import type {
  SensesCapture,
  SensesDevice,
  SensesOverview,
  SensesPairingSession,
  SensesRoutingSession,
  SensesSettings,
} from './types';

const APP_EVENTS_WS_PATH = '/api/apps/events/ws';
const REFRESH_RESOURCES = new Set(['devices', 'pairing', 'settings', 'captures', 'routing', 'view-state']);
const NATIVE_STATUS_ACK_TIMEOUT_MS = 4500;
const NATIVE_COMMAND_FINAL_TIMEOUT_MS = 75000;
const NATIVE_AUDIO_RECORDING_SECONDS = 8;
const NATIVE_AUDIO_RECORDING_MS = NATIVE_AUDIO_RECORDING_SECONDS * 1000;
const TAB_ITEMS = [
  { id: 'devices', label: 'Devices', icon: Glasses },
  { id: 'pairing', label: 'Pairing', icon: KeyRound },
  { id: 'captures', label: 'Captures', icon: Camera },
  { id: 'routing', label: 'Routing', icon: Route },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
  { id: 'debug', label: 'Debug', icon: Wrench },
] as const;

type TabId = (typeof TAB_ITEMS)[number]['id'];
type CaptureFilter = 'all' | 'stored' | 'chat-linked' | 'chat-pending' | 'errors';
type RoutingFilter = 'all' | 'mapped' | 'pending' | 'task';
type NativeCommand = 'refreshNativeStatus' | 'pairGlasses' | 'ask' | 'askAudio' | 'openLogin';
type PendingNativeCommand = {
  command: NativeCommand;
  requestId: string;
  busyLabel: string;
  phase: 'posted' | 'accepted';
  startedAt: number;
  ackDeadlineAt: number;
  finalDeadlineAt: number;
  recordingEndsAt: number | null;
};
type NavigationParams = Record<string, string | boolean | null>;
type ViewFilterState = {
  tab: TabId;
  query: string;
  capture_filter: CaptureFilter;
  routing_filter: RoutingFilter;
};

interface SensesNativeStatus {
  bridge_version?: number;
  host?: string;
  available?: boolean;
  workspace_id?: string;
  base_url?: string;
  updated_at?: string;
  maverick?: {
    status?: string;
    label?: string;
    can_use_senses?: boolean;
  };
  ios?: {
    app?: string;
    auth_mode?: string;
    queue_count?: number;
    last_error?: string | null;
  };
  glasses?: {
    connection?: string;
    label?: string;
    authorization?: string;
    capture?: string;
    is_mock_feed?: boolean;
  };
  capture?: {
    busy?: boolean;
    last_frame_id?: string | null;
    last_frame_summary?: string | null;
    last_audio_id?: string | null;
    last_audio_summary?: string | null;
    senses_status?: string | null;
  };
  actions?: {
    can_pair?: boolean;
    can_ask?: boolean;
    can_ask_audio?: boolean;
    can_refresh?: boolean;
    can_open_login?: boolean;
  };
  bridge_request?: {
    request_id?: string;
    command?: string;
    status?: string;
    message?: string | null;
  } | null;
}

interface SettingsDraft {
  allow_member_pairing: boolean;
  require_admin_for_settings: boolean;
  pairing_code_ttl_seconds: number;
  max_frame_bytes: number;
  max_audio_bytes: number;
  routing_followup_window_seconds: number;
  default_retention_class: string;
  failed_capture_ttl_seconds: number;
}

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: Record<string, { postMessage: (message: unknown) => void } | undefined>;
    };
    __maverickSensesNativeStatus?: SensesNativeStatus;
  }
}

export function App() {
  const [initialViewFilter] = useState(() => viewFilterFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())));
  const [overview, setOverview] = useState<SensesOverview | null>(null);
  const [pairing, setPairing] = useState<SensesPairingSession | null>(null);
  const [query, setQuery] = useState(initialViewFilter.query ?? '');
  const [activeTab, setActiveTab] = useState<TabId>(initialViewFilter.tab || 'devices');
  const [captureFilter, setCaptureFilter] = useState<CaptureFilter>(initialViewFilter.capture_filter || 'all');
  const [routingFilter, setRoutingFilter] = useState<RoutingFilter>(initialViewFilter.routing_filter || 'all');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busyAction, setBusyAction] = useState('');
  const [pendingNativeCommand, setPendingNativeCommand] = useState<PendingNativeCommand | null>(null);
  const [nativeClockNow, setNativeClockNow] = useState(() => Date.now());
  const [settingsDraft, setSettingsDraft] = useState<SettingsDraft | null>(null);
  const nativeHost = useNativeHost();
  const canPersistViewFilter = Boolean(
    overview?.management.can_manage_workspace_devices || overview?.actor.can_manage_workspace_devices,
  );

  const applyRemoteViewFilter = useCallback((filter: Partial<ViewFilterState>) => {
    if (filter.tab) {
      setActiveTab(filter.tab);
    }
    if (filter.query !== undefined) {
      setQuery(filter.query);
    }
    if (filter.capture_filter) {
      setCaptureFilter(filter.capture_filter);
    }
    if (filter.routing_filter) {
      setRoutingFilter(filter.routing_filter);
    }
  }, []);

  const persistViewFilter = useCallback((viewFilter: ViewFilterState) => {
    if (!canPersistViewFilter) {
      return;
    }
    void setViewFilter(viewFilter).catch(() => undefined);
  }, [canPersistViewFilter]);

  const emitCurrentViewState = useCallback((overrides: Partial<ViewFilterState> = {}) => {
    const nextViewFilter = {
      tab: overrides.tab ?? activeTab,
      query: overrides.query ?? query,
      capture_filter: overrides.capture_filter ?? captureFilter,
      routing_filter: overrides.routing_filter ?? routingFilter,
    };
    emitViewStateChanged(nextViewFilter);
    persistViewFilter(nextViewFilter);
  }, [activeTab, captureFilter, persistViewFilter, query, routingFilter]);

  const updateActiveTab = useCallback((tab: TabId) => {
    setActiveTab(tab);
    emitCurrentViewState({ tab });
  }, [emitCurrentViewState]);

  const updateQuery = useCallback((value: string) => {
    setQuery(value);
    emitCurrentViewState({ query: value });
  }, [emitCurrentViewState]);

  const updateCaptureFilter = useCallback((filter: CaptureFilter) => {
    setCaptureFilter(filter);
    emitCurrentViewState({ capture_filter: filter });
  }, [emitCurrentViewState]);

  const updateRoutingFilter = useCallback((filter: RoutingFilter) => {
    setRoutingFilter(filter);
    emitCurrentViewState({ routing_filter: filter });
  }, [emitCurrentViewState]);

  const syncRemoteViewFilter = useCallback(async () => {
    try {
      applyRemoteViewFilter(viewFilterFromParams(await loadViewFilter()));
    } catch {
      return;
    }
  }, [applyRemoteViewFilter]);

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
        metadataValue(device.metadata, 'adapter_id'),
      ].some((value) => value.toLowerCase().includes(normalized));
    });
  }, [overview, query]);

  const filteredCaptures = useMemo(() => {
    return filterCaptures(overview?.captures || [], captureFilter);
  }, [overview, captureFilter]);

  const filteredRoutingSessions = useMemo(() => {
    return filterRoutingSessions(overview?.routing_sessions || [], routingFilter);
  }, [overview, routingFilter]);

  const latestCapture = useMemo(() => newestCapture(overview?.captures || []), [overview]);
  const stats = useMemo(() => {
    const items = overview?.devices || [];
    const captures = overview?.captures || [];
    return {
      total: items.length,
      active: items.filter((device) => device.status === 'active').length,
      revoked: items.filter((device) => device.status === 'revoked').length,
      pendingPairing: overview?.pairing_sessions?.filter((session) => session.status === 'pending').length || 0,
      captures: captures.length,
      routing: overview?.routing_sessions?.length || 0,
      queue: nativeHost.status?.ios?.queue_count ?? 0,
    };
  }, [overview, nativeHost.status]);

  async function refresh(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setBusyAction('refresh');
    }
    try {
      const loaded = await loadOverview();
      setOverview(loaded);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Senses is unavailable.');
    } finally {
      setBusyAction((current) => (current === 'refresh' ? '' : current));
    }
  }

  async function createPairing() {
    setBusyAction('pairing');
    try {
      const created = await startPairing({ deviceKind: 'ios', platform: 'ios' });
      setPairing(created);
      updateActiveTab('pairing');
      setNotice('Pairing created.');
      await refresh({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pairing failed.');
    } finally {
      setBusyAction((current) => (current === 'pairing' ? '' : current));
    }
  }

  async function revoke(device: SensesDevice) {
    setBusyAction(device.device_id);
    try {
      await revokeDevice(device.device_id);
      setNotice('Device revoked.');
      await refresh({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Revocation failed.');
    } finally {
      setBusyAction((current) => (current === device.device_id ? '' : current));
    }
  }

  async function saveSettings() {
    if (!settingsDraft) {
      return;
    }
    setBusyAction('settings');
    try {
      await updateSettings(settingsDraft as Partial<SensesSettings>);
      setNotice('Settings updated.');
      await refresh({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Settings update failed.');
    } finally {
      setBusyAction((current) => (current === 'settings' ? '' : current));
    }
  }

  async function resetRouting(session: SensesRoutingSession) {
    setBusyAction(session.routing_session_id);
    try {
      await resetRoutingSession(session.routing_session_id);
      setNotice('Routing reset.');
      await refresh({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Routing reset failed.');
    } finally {
      setBusyAction((current) => (current === session.routing_session_id ? '' : current));
    }
  }

  async function copyPairingCode() {
    if (!pairing?.code) {
      return;
    }
    await navigator.clipboard?.writeText(pairing.code);
    setNotice('Code copied.');
  }

  function runNativeCommand(command: NativeCommand) {
    const labels: Record<NativeCommand, string> = {
      refreshNativeStatus: 'native-refresh',
      pairGlasses: 'native-pair',
      ask: 'native-ask',
      askAudio: 'native-ask-audio',
      openLogin: 'native-login',
    };
    const requestId = nativeHost.send(command);
    if (!requestId) {
      setError('iOS host is unavailable.');
      return;
    }
    const now = Date.now();
    const busyLabel = labels[command];
    setBusyAction(labels[command]);
    if (command === 'ask' || command === 'askAudio') {
      setError('');
      setNativeClockNow(now);
      setPendingNativeCommand({
        command,
        requestId,
        busyLabel,
        phase: 'posted',
        startedAt: now,
        ackDeadlineAt: now + NATIVE_STATUS_ACK_TIMEOUT_MS,
        finalDeadlineAt: now + NATIVE_COMMAND_FINAL_TIMEOUT_MS,
        recordingEndsAt: command === 'askAudio' ? now + NATIVE_AUDIO_RECORDING_MS : null,
      });
      setNotice(command === 'askAudio' ? 'Voice command posted to iOS. Waiting for recording...' : 'Ask command posted to iOS. Waiting for capture...');
      return;
    }
    setPendingNativeCommand(null);
    setNotice('Command posted to the iOS bridge.');
    window.setTimeout(() => {
      setBusyAction((current) => (current === busyLabel ? '' : current));
    }, 1800);
  }

  useEffect(() => {
    void refresh();
    if (!hasViewFilterValues(initialViewFilter)) {
      void syncRemoteViewFilter();
    }
  }, []);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timer = window.setTimeout(() => setNotice(''), 2600);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!pendingNativeCommand) {
      return undefined;
    }
    const timer = window.setInterval(() => setNativeClockNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [pendingNativeCommand?.requestId]);

  useEffect(() => {
    if (!pendingNativeCommand) {
      return undefined;
    }
    const deadline = pendingNativeCommand.phase === 'posted'
      ? pendingNativeCommand.ackDeadlineAt
      : pendingNativeCommand.finalDeadlineAt;
    const requestId = pendingNativeCommand.requestId;
    const timer = window.setTimeout(() => {
      setPendingNativeCommand((current) => {
        if (!current || current.requestId !== requestId) {
          return current;
        }
        setBusyAction((busy) => (busy === current.busyLabel ? '' : busy));
        setNotice('');
        setError(current.phase === 'posted' ? nativeAckTimeoutMessage(current.command) : nativeFinalTimeoutMessage(current.command));
        return null;
      });
    }, Math.max(0, deadline - Date.now()));
    return () => window.clearTimeout(timer);
  }, [
    pendingNativeCommand?.ackDeadlineAt,
    pendingNativeCommand?.finalDeadlineAt,
    pendingNativeCommand?.phase,
    pendingNativeCommand?.requestId,
  ]);

  useEffect(() => {
    if (!pendingNativeCommand || !nativeHost.status?.updated_at) {
      return;
    }
    const status = nativeHost.status;
    const bridgeRequest = status.bridge_request;
    const updatedAt = status.updated_at;
    if (!updatedAt) {
      return;
    }
    const statusTime = Date.parse(updatedAt);
    const isFreshLegacyStatus = !bridgeRequest
      && !Number.isNaN(statusTime)
      && statusTime >= pendingNativeCommand.startedAt - 500;
    const isFreshLegacyCommandStatus = isFreshLegacyStatus
      && (status.capture?.busy === true || pendingNativeCommand.phase === 'accepted');
    const matchesRequest = bridgeRequest?.request_id === pendingNativeCommand.requestId;
    if (!matchesRequest && !isFreshLegacyCommandStatus) {
      return;
    }

    if (matchesRequest && bridgeRequest?.status === 'failed') {
      setBusyAction((busy) => (busy === pendingNativeCommand.busyLabel ? '' : busy));
      setPendingNativeCommand(null);
      setNotice('');
      setError(bridgeRequest.message || status.ios?.last_error || nativeFinalErrorMessage(pendingNativeCommand.command));
      return;
    }

    if (matchesRequest && bridgeRequest?.status === 'completed') {
      setBusyAction((busy) => (busy === pendingNativeCommand.busyLabel ? '' : busy));
      setPendingNativeCommand(null);
      setError('');
      setNotice(nativeCompletedNotice(pendingNativeCommand.command, status));
      return;
    }

    if (
      pendingNativeCommand.phase === 'posted'
      && ((matchesRequest && bridgeRequest?.status === 'accepted') || (isFreshLegacyStatus && status.capture?.busy))
    ) {
      setPendingNativeCommand((current) => {
        if (!current || current.requestId !== pendingNativeCommand.requestId || current.phase === 'accepted') {
          return current;
        }
        const acceptedAt = Date.now();
        return {
          ...current,
          phase: 'accepted',
          finalDeadlineAt: acceptedAt + NATIVE_COMMAND_FINAL_TIMEOUT_MS,
          recordingEndsAt: current.command === 'askAudio' ? acceptedAt + NATIVE_AUDIO_RECORDING_MS : current.recordingEndsAt,
        };
      });
      setError('');
      setNotice(nativeAcceptedNotice(pendingNativeCommand.command));
      return;
    }

    if (isFreshLegacyStatus && pendingNativeCommand.phase === 'accepted' && status.capture?.busy === false) {
      setBusyAction((busy) => (busy === pendingNativeCommand.busyLabel ? '' : busy));
      setPendingNativeCommand(null);
      setError('');
      setNotice(nativeCompletedNotice(pendingNativeCommand.command, status));
    }
  }, [
    nativeHost.status?.bridge_request?.message,
    nativeHost.status?.bridge_request?.request_id,
    nativeHost.status?.bridge_request?.status,
    nativeHost.status?.capture?.busy,
    nativeHost.status?.ios?.last_error,
    nativeHost.status?.updated_at,
    pendingNativeCommand,
  ]);

  useEffect(() => {
    if (!overview?.settings) {
      return;
    }
    setSettingsDraft({
      allow_member_pairing: overview.settings.allow_member_pairing,
      require_admin_for_settings: overview.settings.require_admin_for_settings,
      pairing_code_ttl_seconds: overview.settings.pairing_code_ttl_seconds,
      max_frame_bytes: overview.settings.max_frame_bytes,
      max_audio_bytes: overview.settings.max_audio_bytes,
      routing_followup_window_seconds: overview.settings.routing_followup_window_seconds,
      default_retention_class: overview.settings.default_retention_class,
      failed_capture_ttl_seconds: overview.settings.failed_capture_ttl_seconds,
    });
  }, [overview?.settings]);

  useEffect(() => {
    if (!nativeHost.status?.updated_at) {
      return;
    }
    void refresh({ silent: true });
  }, [nativeHost.status?.updated_at]);

  useEffect(() => {
    if (pendingNativeCommand || !nativeHost.status?.updated_at || nativeHost.status.capture?.busy) {
      return;
    }
    setBusyAction((current) => (current === 'native-ask' || current === 'native-ask-audio' ? '' : current));
  }, [nativeHost.status?.capture?.busy, nativeHost.status?.updated_at, pendingNativeCommand]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'senses' }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: NavigationParams;
        resource?: string;
        type?: string;
        view_state?: Record<string, unknown>;
      };
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'senses')) {
        const requestedFilter = viewFilterFromParams(payload.params || {});
        if (hasViewFilterValues(requestedFilter)) {
          applyRemoteViewFilter(requestedFilter);
          emitCurrentViewState(requestedFilter);
        }
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'senses') {
        if (!payload.resource || REFRESH_RESOURCES.has(payload.resource)) {
          void refresh({ silent: true });
        }
        if (payload.resource === 'view-state') {
          if (payload.view_state && typeof payload.view_state === 'object') {
            applyRemoteViewFilter(viewFilterFromParams(payload.view_state));
          } else {
            void syncRemoteViewFilter();
          }
        }
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [applyRemoteViewFilter, emitCurrentViewState, syncRemoteViewFilter]);

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
            if (!payload.resource || REFRESH_RESOURCES.has(payload.resource)) {
              void refresh({ silent: true });
            }
            if (payload.resource === 'view-state') {
              void syncRemoteViewFilter();
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
  }, [syncRemoteViewFilter]);

  const dependencyStatus = overview?.dependencies.status || 'unknown';
  const loading = !overview && !error;
  const nativeLastError = nativeHost.status?.ios?.last_error;

  return (
    <main className="senses-shell">
      <header className={`senses-app-header ${nativeHost.available ? 'has-native-actions' : ''}`}>
        <div className="senses-app-title">
          <h1>Senses</h1>
          <span className="senses-title-separator" aria-hidden="true" />
          <p>Device pairing, captures, and routing for the active workspace.</p>
        </div>
        {nativeHost.available ? (
          <NativeHeaderActions
            busyAction={busyAction}
            clockNow={nativeClockNow}
            nativeHostStatus={nativeHost.status}
            onCommand={(command) => runNativeCommand(command)}
            pendingCommand={pendingNativeCommand}
          />
        ) : null}
      </header>

      {(notice || error) && (
        <div className={`senses-toast ${error ? 'is-error' : ''}`} role="status">
          {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{error || notice}</span>
          <button type="button" onClick={() => { setError(''); setNotice(''); }} aria-label="Close">
            <X size={15} />
          </button>
        </div>
      )}

      <div className="senses-content">
        {activeTab === 'devices' && (
          <DevicesTab
            devices={devices}
            loading={loading}
            query={query}
            setQuery={updateQuery}
            canManage={Boolean(overview?.actor.can_manage_workspace_devices)}
            busyAction={busyAction}
            onRevoke={(device) => void revoke(device)}
          />
        )}
        {activeTab === 'pairing' && (
          <PairingTab
            pairing={pairing}
            sessions={overview?.pairing_sessions || []}
            nativeAvailable={nativeHost.available}
            busy={busyAction === 'pairing'}
            onCreate={() => void createPairing()}
            onCopy={() => void copyPairingCode()}
            onNativePair={() => runNativeCommand('pairGlasses')}
          />
        )}
        {activeTab === 'captures' && (
          <CapturesTab
            captures={filteredCaptures}
            totalCount={overview?.captures.length || 0}
            loading={loading}
            filter={captureFilter}
            onFilterChange={updateCaptureFilter}
          />
        )}
        {activeTab === 'routing' && (
          <RoutingTab
            sessions={filteredRoutingSessions}
            totalCount={overview?.routing_sessions.length || 0}
            loading={loading}
            busyAction={busyAction}
            filter={routingFilter}
            onFilterChange={updateRoutingFilter}
            onReset={(session) => void resetRouting(session)}
          />
        )}
        {activeTab === 'settings' && (
          <SettingsTab
            overview={overview}
            draft={settingsDraft}
            setDraft={setSettingsDraft}
            busy={busyAction === 'settings'}
            onSave={() => void saveSettings()}
          />
        )}
        {activeTab === 'debug' && (
          <DebugTab
            dependencyStatus={dependencyStatus}
            latestCapture={latestCapture}
            nativeAvailable={nativeHost.available}
            nativeLastError={nativeLastError}
            nativeStatus={nativeHost.status}
            overview={overview}
            stats={stats}
          />
        )}
      </div>
    </main>
  );
}

function useNativeHost() {
  const [available, setAvailable] = useState(false);
  const [status, setStatus] = useState<SensesNativeStatus | null>(() => window.__maverickSensesNativeStatus || null);

  useEffect(() => {
    function refreshAvailability() {
      setAvailable(hasNativeHost() || window.__maverickSensesNativeStatus?.available === true);
    }
    function applyStatus(detail: unknown) {
      if (detail && typeof detail === 'object') {
        window.__maverickSensesNativeStatus = detail as SensesNativeStatus;
        setStatus(detail as SensesNativeStatus);
      }
      refreshAvailability();
    }
    function handleStatus(event: Event) {
      applyStatus((event as CustomEvent<SensesNativeStatus>).detail);
    }
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { type?: string; status?: unknown; detail?: unknown };
      if (payload.type !== 'maverick.senses.native-status') {
        return;
      }
      applyStatus(payload.status ?? payload.detail);
    }
    window.addEventListener('maverick.senses.native-status', handleStatus);
    window.addEventListener('message', handleMessage);
    refreshAvailability();
    if (window.__maverickSensesNativeStatus) {
      setStatus(window.__maverickSensesNativeStatus);
    }
    if (hasNativeHost()) {
      postNativeCommand('refreshNativeStatus');
    }
    return () => {
      window.removeEventListener('maverick.senses.native-status', handleStatus);
      window.removeEventListener('message', handleMessage);
    };
  }, []);

  const send = useCallback((command: NativeCommand) => {
    if (!hasNativeHost() && window.__maverickSensesNativeStatus?.available !== true) {
      setAvailable(false);
      return null;
    }
    setAvailable(true);
    return postNativeCommand(command);
  }, []);

  return { available, status, send };
}

function hasNativeHost() {
  return Boolean(window.webkit?.messageHandlers?.sensesHost?.postMessage);
}

function postNativeCommand(command: NativeCommand) {
  const requestId = makeRequestId();
  const message = {
    app_id: 'senses',
    command,
    location_href: window.location.href,
    request_id: requestId,
    source: 'senses.frontend',
    type: 'maverick.senses.native-command',
  };
  const directHost = window.webkit?.messageHandlers?.sensesHost;
  if (directHost) {
    directHost.postMessage(message);
    return requestId;
  }
  window.postMessage(message, window.location.origin);
  if (window.parent && window.parent !== window) {
    window.parent.postMessage(message, window.location.origin);
  }
  if (window.top && window.top !== window && window.top !== window.parent) {
    window.top.postMessage(message, window.location.origin);
  }
  return requestId;
}

function emitViewStateChanged(viewFilter: ViewFilterState) {
  window.parent?.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'senses',
      selection: { tab: viewFilter.tab, app_page: viewFilter.tab, view_filter: viewFilter },
    },
    window.location.origin,
  );
  window.parent?.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: 'senses',
      resource: 'view-state',
      view_state: viewFilter,
    },
    window.location.origin,
  );
}

function viewFilterFromParams(params: Record<string, unknown>): Partial<ViewFilterState> {
  const filter: Partial<ViewFilterState> = {};
  const tab = tabFromParams(params);
  const query = queryFromParams(params);
  const captureFilter = captureFilterFromParams(params);
  const routingFilter = routingFilterFromParams(params);
  if (tab) {
    filter.tab = tab;
  }
  if (query !== null) {
    filter.query = query;
  }
  if (captureFilter) {
    filter.capture_filter = captureFilter;
  }
  if (routingFilter) {
    filter.routing_filter = routingFilter;
  }
  return filter;
}

function hasViewFilterValues(filter: Partial<ViewFilterState>) {
  return Boolean(filter.tab || filter.query !== undefined || filter.capture_filter || filter.routing_filter);
}

function tabFromParams(params: Record<string, unknown>): TabId | null {
  const directTab = scalarString(params.tab || params.page_id || params.view || params.section);
  if (isTabId(directTab)) {
    return directTab;
  }
  const appPage = scalarString(params.app_page);
  if (!appPage) {
    return null;
  }
  const firstSegment = appPage.split('/')[0]?.trim();
  return isTabId(firstSegment) ? firstSegment : null;
}

function queryFromParams(params: Record<string, unknown>): string | null {
  const value = params.query ?? params.search ?? params.q;
  if (value === undefined || value === null) {
    return null;
  }
  return scalarString(value);
}

function captureFilterFromParams(params: Record<string, unknown>): CaptureFilter | null {
  const direct = scalarString(
    params.capture_filter || params.captureFilter || params.capture_status || params.captureStatus,
  );
  if (isCaptureFilter(direct)) {
    return direct;
  }
  const status = scalarString(params.status);
  return isCaptureFilter(status) ? status : null;
}

function routingFilterFromParams(params: Record<string, unknown>): RoutingFilter | null {
  const direct = scalarString(
    params.routing_filter || params.routingFilter || params.routing_status || params.routingStatus,
  );
  if (isRoutingFilter(direct)) {
    return direct;
  }
  const status = scalarString(params.status);
  return isRoutingFilter(status) ? status : null;
}

function isTabId(value: string): value is TabId {
  return TAB_ITEMS.some((tab) => tab.id === value);
}

function isCaptureFilter(value: string): value is CaptureFilter {
  return ['all', 'stored', 'chat-linked', 'chat-pending', 'errors'].includes(value);
}

function isRoutingFilter(value: string): value is RoutingFilter {
  return ['all', 'mapped', 'pending', 'task'].includes(value);
}

function scalarString(value: unknown): string {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value).trim();
  }
  return '';
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: 'good' | 'muted' | 'pending' }) {
  return (
    <div className={`metric ${tone ? `tone-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusTile({
  icon: Icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  tone?: 'good' | 'warn' | 'danger' | 'muted';
}) {
  return (
    <article className={`status-tile ${tone ? `tone-${tone}` : ''}`}>
      <div className="tile-icon" aria-hidden="true">
        <Icon size={17} />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <p>{detail}</p>
      </div>
    </article>
  );
}

function NativeHeaderActions({
  busyAction,
  clockNow,
  nativeHostStatus,
  onCommand,
  pendingCommand,
}: {
  busyAction: string;
  clockNow: number;
  nativeHostStatus: SensesNativeStatus | null;
  onCommand: (command: NativeCommand) => void;
  pendingCommand: PendingNativeCommand | null;
}) {
  const nativeCaptureBusy = nativeHostStatus?.capture?.busy === true;
  const pendingCaptureCommand = pendingCommand?.command === 'ask' || pendingCommand?.command === 'askAudio';
  const captureControlsBusy = nativeCaptureBusy || Boolean(pendingCaptureCommand);
  const actionStatus = nativeActionStatus(pendingCommand, nativeHostStatus, clockNow);
  const askLabel = pendingCommand?.command === 'ask' ? nativeActionButtonLabel(pendingCommand, clockNow) : 'Ask';
  const voiceLabel = pendingCommand?.command === 'askAudio' ? nativeActionButtonLabel(pendingCommand, clockNow) : 'Voice';
  return (
    <div className="native-header-actions" aria-label="iOS controls">
      {actionStatus ? (
        <span className={`native-action-status tone-${actionStatus.tone}`} role="status">
          <Clock3 size={13} />
          <span>{actionStatus.label}</span>
        </span>
      ) : null}
      <button
        className="tool-button"
        type="button"
        onClick={() => onCommand('pairGlasses')}
        disabled={captureControlsBusy || nativeHostStatus?.actions?.can_pair === false || busyAction === 'native-pair'}
      >
        <Glasses size={16} />
        <span>Pair glasses</span>
      </button>
      <button
        className="tool-button primary-tool"
        type="button"
        onClick={() => onCommand('ask')}
        disabled={captureControlsBusy || nativeHostStatus?.actions?.can_ask === false}
      >
        <Send size={16} />
        <span>{askLabel}</span>
      </button>
      <button
        className="tool-button"
        type="button"
        onClick={() => onCommand('askAudio')}
        disabled={captureControlsBusy || nativeHostStatus?.actions?.can_ask_audio === false}
      >
        <Mic size={16} />
        <span>{voiceLabel}</span>
      </button>
      <button
        className="tool-button"
        type="button"
        onClick={() => onCommand('refreshNativeStatus')}
        disabled={busyAction === 'native-refresh'}
      >
        <RefreshCw size={16} />
        <span>Native refresh</span>
      </button>
      <button
        className="tool-button"
        type="button"
        onClick={() => onCommand('openLogin')}
        disabled={busyAction === 'native-login'}
      >
        <LogIn size={16} />
        <span>Login</span>
      </button>
    </div>
  );
}

function nativeActionStatus(
  pendingCommand: PendingNativeCommand | null,
  nativeHostStatus: SensesNativeStatus | null,
  now: number,
) {
  if (!pendingCommand) {
    return null;
  }
  if (pendingCommand.phase === 'posted') {
    return { label: `${nativeCommandName(pendingCommand.command)} posted to bridge`, tone: 'warn' as const };
  }
  if (pendingCommand.command === 'askAudio') {
    const remaining = pendingCommand.recordingEndsAt ? secondsRemaining(pendingCommand.recordingEndsAt, now) : 0;
    if (remaining > 0 && nativeHostStatus?.capture?.busy !== false) {
      return { label: `Recording ${remaining}s`, tone: 'warn' as const };
    }
    const backendStatus = nativeHostStatus?.capture?.senses_status;
    return { label: backendStatus ? `Sending ${backendStatus}` : 'Sending audio', tone: 'warn' as const };
  }
  const backendStatus = nativeHostStatus?.capture?.senses_status;
  return { label: backendStatus ? `Capture ${backendStatus}` : 'Capturing', tone: 'warn' as const };
}

function nativeActionButtonLabel(pendingCommand: PendingNativeCommand, now: number) {
  if (pendingCommand.phase === 'posted') {
    return 'Waiting...';
  }
  if (pendingCommand.command === 'askAudio') {
    const remaining = pendingCommand.recordingEndsAt ? secondsRemaining(pendingCommand.recordingEndsAt, now) : 0;
    return remaining > 0 ? `Voice ${remaining}s` : 'Sending...';
  }
  return 'Capturing...';
}

function nativeAcceptedNotice(command: NativeCommand) {
  if (command === 'askAudio') {
    return 'iOS accepted Voice. Recording...';
  }
  if (command === 'ask') {
    return 'iOS accepted Ask. Capturing...';
  }
  return 'iOS accepted the command.';
}

function nativeCompletedNotice(command: NativeCommand, status: SensesNativeStatus) {
  const backendStatus = status.capture?.senses_status;
  if (command === 'askAudio') {
    return backendStatus ? `Voice finished: ${backendStatus}.` : 'Voice finished.';
  }
  if (command === 'ask') {
    return backendStatus ? `Ask finished: ${backendStatus}.` : 'Ask finished.';
  }
  return 'Native command finished.';
}

function nativeAckTimeoutMessage(command: NativeCommand) {
  return `${nativeCommandName(command)} was posted to iOS, but native did not acknowledge it. Try again from the iPhone app.`;
}

function nativeFinalTimeoutMessage(command: NativeCommand) {
  return `${nativeCommandName(command)} was accepted by iOS, but no final native status arrived. Check the iPhone app and try again.`;
}

function nativeFinalErrorMessage(command: NativeCommand) {
  return `${nativeCommandName(command)} failed in the iOS app.`;
}

function nativeCommandName(command: NativeCommand) {
  if (command === 'askAudio') {
    return 'Voice';
  }
  if (command === 'ask') {
    return 'Ask';
  }
  return 'Command';
}

function secondsRemaining(deadline: number, now: number) {
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}

function DevicesTab({
  devices,
  loading,
  query,
  setQuery,
  canManage,
  busyAction,
  onRevoke,
}: {
  devices: SensesDevice[];
  loading: boolean;
  query: string;
  setQuery: (value: string) => void;
  canManage: boolean;
  busyAction: string;
  onRevoke: (device: SensesDevice) => void;
}) {
  return (
    <section className="senses-panel devices-panel">
      <div className="panel-heading">
        <div>
          <h2>Devices</h2>
          <p>{canManage ? 'Workspace' : 'Personal'}</p>
        </div>
        <label className="senses-search">
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search" />
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
              onRevoke={() => onRevoke(device)}
            />
          ))}
        </div>
      ) : (
        <EmptyState icon={Unplug} label="No registered devices" />
      )}
    </section>
  );
}

function DeviceRow({ device, busy, onRevoke }: { device: SensesDevice; busy: boolean; onRevoke: () => void }) {
  const Icon = deviceIcon(device);
  const adapter = metadataValue(device.metadata, 'adapter_id') || metadataValue(device.metadata, 'adapter') || 'default';
  const scopes = metadataList(device.metadata, ['scopes', 'capabilities']);
  return (
    <article className={`data-row device-row is-${device.status}`}>
      <div className="device-icon" aria-hidden="true">
        <Icon size={19} />
      </div>
      <div className="row-main">
        <div className="row-title">
          <h3>{device.display_name}</h3>
          <span className={`status-pill is-${device.status}`}>{device.status}</span>
        </div>
        <div className="row-meta">
          <span>{device.platform}</span>
          <span>{device.device_kind}</span>
          <span>{adapter}</span>
          <span>{formatDate(device.last_seen_at || device.paired_at)}</span>
        </div>
        <div className="capability-list">
          {scopes.length ? scopes.slice(0, 5).map((scope) => <span key={scope}>{scope}</span>) : <span>registry</span>}
        </div>
      </div>
      <button
        className="icon-button danger"
        type="button"
        onClick={onRevoke}
        title="Revoke"
        aria-label={`Revoke ${device.display_name}`}
        disabled={!device.can_revoke || busy}
      >
        <X size={16} />
      </button>
    </article>
  );
}

function PairingTab({
  pairing,
  sessions,
  nativeAvailable,
  busy,
  onCreate,
  onCopy,
  onNativePair,
}: {
  pairing: SensesPairingSession | null;
  sessions: SensesPairingSession[];
  nativeAvailable: boolean;
  busy: boolean;
  onCreate: () => void;
  onCopy: () => void;
  onNativePair: () => void;
}) {
  const visiblePairing = pairing || sessions.find((session) => session.status === 'pending') || null;
  return (
    <section className="senses-panel pairing-workspace">
      <div className="panel-heading">
        <div>
          <h2>Pairing</h2>
          <p>{visiblePairing ? `${visiblePairing.status} - ${formatDuration(secondsUntil(visiblePairing.expires_at))}` : 'no open session'}</p>
        </div>
        <div className="panel-actions">
          {nativeAvailable ? (
            <button className="tool-button" type="button" onClick={onNativePair}>
              <Glasses size={16} />
              <span>Glasses</span>
            </button>
          ) : null}
          <button className="primary-button" type="button" onClick={onCreate} disabled={busy}>
            <Plus size={16} />
            <span>New</span>
          </button>
        </div>
      </div>

      <div className="pairing-layout">
        {visiblePairing ? (
          <div className="pairing-code-box large">
            <span className="code-label">Code</span>
            <button className="pairing-code" type="button" onClick={onCopy} title="Copy code">
              <span>{visiblePairing.code || 'hidden'}</span>
              <Copy size={16} />
            </button>
            <span className="pairing-expiry">
              <Clock3 size={14} />
              {formatDate(visiblePairing.expires_at)}
            </span>
          </div>
        ) : (
          <EmptyState icon={Clock3} label="No open pairing" compact />
        )}

        <div className="qr-payload" aria-label="Payload pairing">
          <div className="qr-mark">
            <KeyRound size={26} />
          </div>
          <pre>{visiblePairing ? JSON.stringify(visiblePairing.qr_payload || {}, null, 2) : '{}'}</pre>
        </div>
      </div>

      <PendingPairings sessions={sessions} />
    </section>
  );
}

function PendingPairings({ sessions }: { sessions: SensesPairingSession[] }) {
  if (!sessions.length) {
    return null;
  }
  return (
    <div className="pending-list">
      {sessions.slice(0, 8).map((session) => (
        <div className="pending-row" key={session.pairing_id}>
          <span>{compactId(session.pairing_id)}</span>
          <span>{session.device_kind || 'ios'}</span>
          <span className={`status-pill is-${session.status}`}>{session.status}</span>
          <time>{formatDate(session.expires_at)}</time>
        </div>
      ))}
    </div>
  );
}

function CapturesTab({
  captures,
  totalCount,
  loading,
  filter,
  onFilterChange,
}: {
  captures: SensesCapture[];
  totalCount: number;
  loading: boolean;
  filter: CaptureFilter;
  onFilterChange: (filter: CaptureFilter) => void;
}) {
  return (
    <section className="senses-panel table-panel">
      <div className="panel-heading">
        <div>
          <h2>Captures</h2>
          <p>{captures.length}/{totalCount} record</p>
        </div>
        <SegmentedControl<CaptureFilter>
          value={filter}
          onChange={onFilterChange}
          options={[
            { id: 'all', label: 'All' },
            { id: 'stored', label: 'Stored' },
            { id: 'chat-linked', label: 'Chat' },
            { id: 'chat-pending', label: 'Pending' },
            { id: 'errors', label: 'Errors' },
          ]}
        />
      </div>
      {loading ? (
        <TableSkeleton />
      ) : captures.length ? (
        <div className="table-list capture-list">
          {captures.map((capture) => (
            <article className="table-row capture-row" key={capture.capture_id}>
              <div>
                <strong>{compactId(capture.capture_id)}</strong>
                <span>{capture.device_id}</span>
                {capture.origin?.kind === 'meta_glasses' ? (
                  <span className="capture-origin">
                    <Glasses size={12} />
                    {capture.origin.label}
                  </span>
                ) : null}
              </div>
              <div>
                <span className={`status-pill is-${capture.status}`}>{capture.status}</span>
                <span>{capture.retention_class}</span>
              </div>
              <div>
                <span>{capture.content_type}</span>
                <span>{formatBytes(capture.storage.size_bytes)}</span>
              </div>
              <div className="link-stack">
                <CaptureStorageLink capture={capture} />
                <CaptureChatLink capture={capture} />
              </div>
              <time>{formatDate(capture.captured_at)}</time>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState icon={Camera} label="No captures" />
      )}
    </section>
  );
}

function CaptureChatLink({ capture }: { capture: SensesCapture }) {
  const label = capture.chat.label || (capture.chat.deep_link ? 'Chat linked' : 'Chat pending');
  if (capture.chat.deep_link) {
    return (
      <a className="chat-status-link is-linked" href={capture.chat.deep_link}>
        <MessageSquare size={14} />
        <span>{label}</span>
      </a>
    );
  }
  return (
    <span className="chat-status-link is-pending">
      <MessageSquare size={14} />
      <span>{label}</span>
    </span>
  );
}

function CaptureStorageLink({ capture }: { capture: SensesCapture }) {
  const href = storageHrefForCapture(capture);
  if (!href) {
    return <span>Storage pending</span>;
  }
  return (
    <a href={href}>
      <HardDrive size={14} />
      <span>Storage</span>
    </a>
  );
}

function storageHrefForCapture(capture: SensesCapture) {
  const fileId = capture.storage.storage_file_id?.trim();
  if (fileId) {
    return `/app/storage/files/${encodeURIComponent(fileId)}`;
  }
  const workspaceRelativePath = capture.storage.workspace_relative_path?.trim();
  if (workspaceRelativePath) {
    return `/app/storage?workspace_relative_path=${encodeURIComponent(workspaceRelativePath)}`;
  }
  return '';
}

function RoutingTab({
  sessions,
  totalCount,
  loading,
  busyAction,
  filter,
  onFilterChange,
  onReset,
}: {
  sessions: SensesRoutingSession[];
  totalCount: number;
  loading: boolean;
  busyAction: string;
  filter: RoutingFilter;
  onFilterChange: (filter: RoutingFilter) => void;
  onReset: (session: SensesRoutingSession) => void;
}) {
  return (
    <section className="senses-panel table-panel">
      <div className="panel-heading">
        <div>
          <h2>Routing</h2>
          <p>{sessions.length}/{totalCount} sessions</p>
        </div>
        <SegmentedControl<RoutingFilter>
          value={filter}
          onChange={onFilterChange}
          options={[
            { id: 'all', label: 'All' },
            { id: 'mapped', label: 'Mapped' },
            { id: 'pending', label: 'Pending' },
            { id: 'task', label: 'Task' },
          ]}
        />
      </div>
      {loading ? (
        <TableSkeleton />
      ) : sessions.length ? (
        <div className="table-list routing-list">
          {sessions.map((session) => {
            const mappingStatus = routingMappingStatus(session);
            return (
              <article className="routing-card" key={session.routing_session_id}>
                <div className="routing-header">
                  <div>
                    <strong>{compactId(session.routing_session_id)}</strong>
                    <span>{session.device_id}</span>
                  </div>
                  <div className="routing-actions">
                    <span className={`status-pill is-${mappingStatus}`}>{routingMappingLabel(session)}</span>
                    <button
                      className="tool-button"
                      type="button"
                      onClick={() => onReset(session)}
                      disabled={busyAction === session.routing_session_id}
                    >
                      <RotateCcw size={15} />
                      <span>Reset</span>
                    </button>
                  </div>
                </div>
                <dl className="detail-grid">
                  <div>
                    <dt>Primary thread</dt>
                    <dd>{linkOrEmpty(session.primary_chat.deep_link, session.primary_thread_id)}</dd>
                  </div>
                  <div>
                    <dt>Active task</dt>
                    <dd>{linkOrEmpty(session.active_task_chat.deep_link, session.active_task_thread_id)}</dd>
                  </div>
                  <div>
                    <dt>Last thread</dt>
                    <dd>{linkOrEmpty(session.last_chat.deep_link, session.last_thread_id)}</dd>
                  </div>
                  <div>
                    <dt>Last turn</dt>
                    <dd>{session.last_turn_id ? compactId(session.last_turn_id) : 'none'}</dd>
                  </div>
                  <div>
                    <dt>Routing</dt>
                    <dd>{session.last_routing_kind || 'none'}</dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState icon={Route} label="No routing sessions" />
      )}
    </section>
  );
}

function SettingsTab({
  overview,
  draft,
  setDraft,
  busy,
  onSave,
}: {
  overview: SensesOverview | null;
  draft: SettingsDraft | null;
  setDraft: (draft: SettingsDraft) => void;
  busy: boolean;
  onSave: () => void;
}) {
  const canSave = Boolean(overview?.actor.can_manage_workspace_devices);
  return (
    <section className="senses-panel settings-panel">
      <div className="panel-heading">
        <div>
          <h2>Settings</h2>
          <p>{overview?.settings.auth_mode || 'user_session_mvp'}</p>
        </div>
        <SlidersHorizontal size={18} />
      </div>
      {draft ? (
        <div className="settings-form">
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.allow_member_pairing}
              onChange={(event) => setDraft({ ...draft, allow_member_pairing: event.target.checked })}
            />
            <span>Member pairing</span>
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.require_admin_for_settings}
              onChange={(event) => setDraft({ ...draft, require_admin_for_settings: event.target.checked })}
            />
            <span>Admin settings</span>
          </label>
          <NumberField
            label="Pairing TTL"
            value={draft.pairing_code_ttl_seconds}
            suffix="s"
            onChange={(value) => setDraft({ ...draft, pairing_code_ttl_seconds: value })}
          />
          <NumberField
            label="Max frame"
            value={draft.max_frame_bytes}
            suffix="bytes"
            onChange={(value) => setDraft({ ...draft, max_frame_bytes: value })}
          />
          <NumberField
            label="Max audio"
            value={draft.max_audio_bytes}
            suffix="bytes"
            onChange={(value) => setDraft({ ...draft, max_audio_bytes: value })}
          />
          <NumberField
            label="Routing window"
            value={draft.routing_followup_window_seconds}
            suffix="s"
            onChange={(value) => setDraft({ ...draft, routing_followup_window_seconds: value })}
          />
          <label className="field-row">
            <span>Retention</span>
            <input
              value={draft.default_retention_class}
              onChange={(event) => setDraft({ ...draft, default_retention_class: event.target.value })}
            />
          </label>
          <NumberField
            label="Failed capture TTL"
            value={draft.failed_capture_ttl_seconds}
            suffix="s"
            onChange={(value) => setDraft({ ...draft, failed_capture_ttl_seconds: value })}
          />
          <button className="primary-button save-button" type="button" onClick={onSave} disabled={!canSave || busy}>
            <ShieldCheck size={16} />
            <span>Save</span>
          </button>
        </div>
      ) : (
        <EmptyState icon={SettingsIcon} label="Settings not loaded" compact />
      )}
    </section>
  );
}

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: Array<{ id: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented-control" role="group" aria-label="Filter">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          className={option.id === value ? 'is-active' : ''}
          onClick={() => onChange(option.id)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function DebugTab({
  dependencyStatus,
  latestCapture,
  nativeAvailable,
  nativeLastError,
  nativeStatus,
  overview,
  stats,
}: {
  dependencyStatus: string;
  latestCapture: SensesCapture | null;
  nativeAvailable: boolean;
  nativeLastError?: string | null;
  nativeStatus: SensesNativeStatus | null;
  overview: SensesOverview | null;
  stats: {
    total: number;
    active: number;
    revoked: number;
    pendingPairing: number;
    captures: number;
    routing: number;
    queue: number;
  };
}) {
  return (
    <div className="debug-grid">
      <section className="live-dashboard" aria-label="Live dashboard">
        <StatusTile
          icon={Radio}
          label="Maverick"
          value={nativeStatus?.maverick?.label || nativeStatus?.maverick?.status || dependencyStatus}
          detail={overview?.actor.authenticated ? overview.actor.workspace_role || 'session' : 'session not verified'}
          tone={dependencyStatus === 'resolved' ? 'good' : 'warn'}
        />
        <StatusTile
          icon={Smartphone}
          label="iOS app"
          value={nativeAvailable ? nativeStatus?.ios?.app || 'Maverick iOS' : 'Browser/PWA'}
          detail={nativeAvailable ? nativeStatus?.ios?.auth_mode || 'web session' : 'host unavailable'}
          tone={nativeAvailable ? 'good' : 'muted'}
        />
        <StatusTile
          icon={Glasses}
          label="Glasses"
          value={nativeStatus?.glasses?.label || nativeStatus?.glasses?.connection || 'remote'}
          detail={nativeStatus?.glasses?.authorization || 'no local driver'}
          tone={nativeStatus?.actions?.can_ask ? 'good' : nativeAvailable ? 'warn' : 'muted'}
        />
        <StatusTile
          icon={Camera}
          label="Capture"
          value={nativeStatus?.glasses?.capture || nativeStatus?.capture?.senses_status || latestCapture?.status || 'idle'}
          detail={nativeStatus?.capture?.last_frame_summary || nativeStatus?.capture?.last_audio_summary || latestCapture?.capture_id || 'no capture'}
          tone={nativeStatus?.capture?.busy ? 'warn' : latestCapture ? 'good' : 'muted'}
        />
        <StatusTile
          icon={ListChecks}
          label="Senses queue"
          value={String(stats.queue)}
          detail={nativeStatus?.capture?.senses_status || `${stats.captures} captures`}
          tone={stats.queue > 0 ? 'warn' : 'good'}
        />
        <StatusTile
          icon={AlertTriangle}
          label="Last error"
          value={nativeLastError ? 'present' : overview?.dependencies.blocked_reason ? 'dependency' : 'none'}
          detail={nativeLastError || overview?.dependencies.blocked_reason || latestCapture?.error_code || 'no error'}
          tone={nativeLastError || overview?.dependencies.blocked_reason ? 'danger' : 'muted'}
        />
      </section>

      <section className="senses-metrics" aria-label="Senses metrics">
        <Metric label="Devices" value={stats.total} />
        <Metric label="Active" value={stats.active} tone="good" />
        <Metric label="Revoked" value={stats.revoked} tone="muted" />
        <Metric label="Pairing" value={stats.pendingPairing} tone="pending" />
        <Metric label="Captures" value={stats.captures} />
        <Metric label="Routing" value={stats.routing} />
      </section>

      <section className="senses-panel diagnostics-panel">
        <div className="panel-heading">
          <div>
            <h2>Diagnostics</h2>
            <p>{nativeAvailable ? 'iOS host' : 'browser/PWA'}</p>
          </div>
          <Wrench size={18} />
        </div>
        <dl className="policy-list">
          <div>
            <dt>Backend</dt>
            <dd>{overview?.ok ? 'ok' : 'unknown'}</dd>
          </div>
          <div>
            <dt>Storage</dt>
            <dd>{overview?.dependencies.status || 'unknown'}</dd>
          </div>
          <div>
            <dt>Runtime</dt>
            <dd>{overview?.routing_sessions.length ? 'mapped' : 'idle'}</dd>
          </div>
          <div>
            <dt>Auth mode</dt>
            <dd>{overview?.settings.auth_mode || 'unknown'}</dd>
          </div>
          <div>
            <dt>Device ingress</dt>
            <dd>{overview?.settings.device_ingress_enabled ? 'on' : 'off'}</dd>
          </div>
          <div>
            <dt>iOS bridge</dt>
            <dd>{nativeAvailable ? `v${nativeStatus?.bridge_version || 1}` : 'none'}</dd>
          </div>
          <div>
            <dt>Last native</dt>
            <dd>{nativeStatus?.updated_at ? formatDate(nativeStatus.updated_at) : 'never'}</dd>
          </div>
          <div>
            <dt>Privacy</dt>
            <dd>no secrets</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function NumberField({
  label,
  value,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  suffix: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="field-row">
      <span>{label}</span>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(event) => onChange(Number(event.target.value || 0))}
      />
      <small>{suffix}</small>
    </label>
  );
}

function EmptyState({ icon: Icon, label, compact }: { icon: LucideIcon; label: string; compact?: boolean }) {
  return (
    <div className={`empty-state ${compact ? 'compact-empty' : ''}`}>
      <Icon size={22} />
      <span>{label}</span>
    </div>
  );
}

function DeviceSkeleton() {
  return (
    <div className="device-list">
      {[0, 1, 2].map((item) => (
        <div className="data-row device-row skeleton" key={item}>
          <span className="device-icon" />
          <span className="skeleton-lines" />
        </div>
      ))}
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="table-list">
      {[0, 1, 2, 3].map((item) => (
        <div className="table-row skeleton" key={item}>
          <span className="skeleton-lines" />
          <span className="skeleton-lines" />
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

function newestCapture(captures: SensesCapture[]) {
  return captures.slice().sort((left, right) => Date.parse(right.captured_at) - Date.parse(left.captured_at))[0] || null;
}

function metadataValue(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

function metadataList(metadata: Record<string, unknown>, keys: string[]) {
  const values: string[] = [];
  for (const key of keys) {
    const value = metadata[key];
    if (Array.isArray(value)) {
      values.push(...value.map(String));
    } else if (typeof value === 'string') {
      values.push(...value.split(',').map((item) => item.trim()).filter(Boolean));
    }
  }
  return Array.from(new Set(values));
}

function filterCaptures(captures: SensesCapture[], filter: CaptureFilter) {
  return captures.filter((capture) => {
    if (filter === 'stored') {
      return capture.storage.status === 'stored';
    }
    if (filter === 'chat-linked') {
      return Boolean(capture.chat.deep_link);
    }
    if (filter === 'chat-pending') {
      return !capture.chat.deep_link;
    }
    if (filter === 'errors') {
      return Boolean(capture.error_code) || capture.status.includes('failed') || capture.status.includes('error');
    }
    return true;
  });
}

function filterRoutingSessions(sessions: SensesRoutingSession[], filter: RoutingFilter) {
  return sessions.filter((session) => {
    const status = routingMappingStatus(session);
    if (filter === 'mapped') {
      return status === 'mapped' || status === 'task';
    }
    if (filter === 'pending') {
      return status === 'pending';
    }
    if (filter === 'task') {
      return status === 'task';
    }
    return true;
  });
}

function routingMappingStatus(session: SensesRoutingSession): 'mapped' | 'pending' | 'task' {
  if (session.active_task_thread_id) {
    return 'task';
  }
  if (session.primary_thread_id || session.last_thread_id) {
    return 'mapped';
  }
  return 'pending';
}

function routingMappingLabel(session: SensesRoutingSession) {
  const status = routingMappingStatus(session);
  if (status === 'task') {
    return 'Task mapped';
  }
  if (status === 'mapped') {
    return 'Chat mapped';
  }
  return 'Chat pending';
}

function linkOrEmpty(deepLink: string | null, label: string | null) {
  if (!deepLink || !label) {
    return 'none';
  }
  return (
    <a href={deepLink}>
      <Link2 size={13} />
      <span>{compactId(label)}</span>
    </a>
  );
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'never';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatBytes(value: number | null | undefined) {
  const bytes = Number(value || 0);
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function secondsUntil(value: string | null | undefined) {
  if (!value) {
    return 0;
  }
  const ms = Date.parse(value) - Date.now();
  return Math.max(0, Math.floor(ms / 1000));
}

function formatDuration(seconds: number) {
  if (seconds <= 0) {
    return 'expired';
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function compactId(value: string | null | undefined) {
  if (!value) {
    return 'none';
  }
  if (value.length <= 18) {
    return value;
  }
  return `${value.slice(0, 10)}...${value.slice(-6)}`;
}

function makeRequestId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
