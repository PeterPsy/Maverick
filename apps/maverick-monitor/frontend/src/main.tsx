import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { loadSnapshot, updateSettings } from './api';
import type { AggregateRow, MonitorPayload, ProcessRow } from './types';
import './styles.css';

type Tab = 'machine' | 'apps' | 'workspaces' | 'processes';

const tabs: { id: Tab; label: string }[] = [
  { id: 'machine', label: 'Macchina' },
  { id: 'apps', label: 'App' },
  { id: 'workspaces', label: 'Workspace' },
  { id: 'processes', label: 'Processi' }
];

function bytes(value: number | undefined): string {
  const amount = value || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = amount;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function percent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'warn' | 'bad' }) {
  return (
    <div className={`metric ${tone || ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Bar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(value, 100));
  return (
    <div className="bar" aria-label={`${clamped}%`}>
      <div style={{ width: `${clamped}%` }} />
    </div>
  );
}

function Header({
  payload,
  autoRefresh,
  onRefresh,
  onAutoRefresh
}: {
  payload: MonitorPayload | null;
  autoRefresh: boolean;
  onRefresh: () => void;
  onAutoRefresh: (enabled: boolean) => void;
}) {
  return (
    <header className="topbar">
      <div>
        <h1>Maverick Monitor</h1>
        <p>{payload ? `${payload.snapshot.workspace_id} · ${new Date(payload.snapshot.captured_at).toLocaleString()}` : 'Snapshot in corso'}</p>
      </div>
      <div className="controls">
        <label className="toggle">
          <input type="checkbox" checked={autoRefresh} onChange={(event) => onAutoRefresh(event.target.checked)} />
          <span>Auto</span>
        </label>
        <button type="button" onClick={onRefresh}>Refresh</button>
      </div>
    </header>
  );
}

function MachineView({ payload }: { payload: MonitorPayload }) {
  const machine = payload.snapshot.machine;
  const service = payload.snapshot.service;
  return (
    <section className="view">
      <div className="metricGrid">
        <Metric label="RAM usata" value={`${bytes(machine.memory_used_bytes)} / ${bytes(machine.memory_total_bytes)}`} tone={machine.memory_used_percent > 85 ? 'bad' : machine.memory_used_percent > 70 ? 'warn' : undefined} />
        <Metric label="Disco usato" value={`${bytes(machine.disk_used_bytes)} / ${bytes(machine.disk_total_bytes)}`} tone={machine.disk_used_percent > 85 ? 'bad' : machine.disk_used_percent > 70 ? 'warn' : undefined} />
        <Metric label="Load average" value={machine.load_average.join(' · ')} />
        <Metric label="CPU" value={`${machine.cpu_count} core`} />
        <Metric label="App installate" value={String(service.installed_app_count || 0)} />
        <Metric label="Workspace" value={String(service.workspace_count || 0)} />
        <Metric label="Runtime" value={bytes(service.runtime_bytes)} />
        <Metric label="Log" value={bytes(service.log_bytes)} />
      </div>
      <div className="split">
        <div className="panel">
          <h2>Pressione</h2>
          <div className="pressureRow"><span>RAM</span><Bar value={machine.memory_used_percent} /><strong>{percent(machine.memory_used_percent)}</strong></div>
          <div className="pressureRow"><span>Disco</span><Bar value={machine.disk_used_percent} /><strong>{percent(machine.disk_used_percent)}</strong></div>
        </div>
        <div className="panel">
          <h2>Segnali</h2>
          <div className="insights">
            {payload.snapshot.insights.map((item) => (
              <div className={`insight ${item.level}`} key={`${item.title}-${item.detail}`}>
                <strong>{item.title}</strong>
                <span>{item.detail}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function AggregatesView({ rows, mode }: { rows: AggregateRow[]; mode: 'apps' | 'workspaces' }) {
  return (
    <section className="view">
      <table>
        <thead>
          <tr>
            <th>{mode === 'apps' ? 'App' : 'Workspace'}</th>
            <th>CPU</th>
            <th>RAM RSS</th>
            <th>Processi</th>
            {mode === 'workspaces' && <th>Disco</th>}
            {mode === 'workspaces' && <th>Data</th>}
            {mode === 'workspaces' && <th>Runtime</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td><strong>{row.id}</strong></td>
              <td>{percent(row.cpu_percent)}</td>
              <td>{bytes(row.rss_bytes)}</td>
              <td>{row.process_count}</td>
              {mode === 'workspaces' && <td>{bytes(row.disk_bytes)}</td>}
              {mode === 'workspaces' && <td>{bytes(row.data_bytes)}</td>}
              {mode === 'workspaces' && <td>{bytes(row.runtime_bytes)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ProcessView({ rows }: { rows: ProcessRow[] }) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => `${row.pid} ${row.app_id} ${row.workspace_id} ${row.command}`.toLowerCase().includes(needle));
  }, [query, rows]);
  return (
    <section className="view">
      <input className="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filtra processi, app, workspace" />
      <table>
        <thead>
          <tr>
            <th>PID</th>
            <th>App</th>
            <th>Workspace</th>
            <th>CPU</th>
            <th>RAM RSS</th>
            <th>Comando</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((row) => (
            <tr key={row.pid}>
              <td>{row.pid}</td>
              <td>{row.app_id}</td>
              <td>{row.workspace_id}</td>
              <td>{percent(row.cpu_percent)}</td>
              <td>{bytes(row.rss_bytes)}</td>
              <td className="command" title={row.command}>{row.command}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function App() {
  const [payload, setPayload] = useState<MonitorPayload | null>(null);
  const [tab, setTab] = useState<Tab>('machine');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState('');

  const refresh = async () => {
    try {
      const next = await loadSnapshot();
      setPayload(next);
      if (tabs.some((item) => item.id === next.state.selected_tab)) setTab(next.state.selected_tab as Tab);
      setError('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Errore di monitoraggio');
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!autoRefresh || !payload) return;
    const timer = window.setInterval(refresh, payload.state.refresh_seconds * 1000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, payload?.state.refresh_seconds]);

  const selectTab = async (next: Tab) => {
    setTab(next);
    try {
      await updateSettings({ selected_tab: next });
    } catch {
      return;
    }
  };

  return (
    <main>
      <Header payload={payload} autoRefresh={autoRefresh} onRefresh={refresh} onAutoRefresh={setAutoRefresh} />
      <nav className="tabs" aria-label="Monitor views">
        {tabs.map((item) => (
          <button className={tab === item.id ? 'active' : ''} type="button" key={item.id} onClick={() => selectTab(item.id)}>
            {item.label}
          </button>
        ))}
      </nav>
      {error && <div className="error">{error}</div>}
      {!payload && !error && <div className="loading">Caricamento metriche</div>}
      {payload && tab === 'machine' && <MachineView payload={payload} />}
      {payload && tab === 'apps' && <AggregatesView rows={payload.snapshot.apps} mode="apps" />}
      {payload && tab === 'workspaces' && <AggregatesView rows={payload.snapshot.workspaces} mode="workspaces" />}
      {payload && tab === 'processes' && <ProcessView rows={payload.snapshot.processes} />}
    </main>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(<App />);
