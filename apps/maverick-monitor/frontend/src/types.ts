export type Machine = {
  cpu_count: number;
  load_average: number[];
  memory_total_bytes: number;
  memory_used_bytes: number;
  memory_available_bytes: number;
  memory_used_percent: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
  disk_used_percent: number;
};

export type AggregateRow = {
  id: string;
  cpu_percent: number;
  rss_bytes: number;
  process_count: number;
  disk_bytes?: number;
  data_bytes?: number;
  runtime_bytes?: number;
  generated_bytes?: number;
  uploaded_bytes?: number;
};

export type ProcessRow = {
  pid: number;
  command: string;
  cwd: string;
  app_id: string;
  workspace_id: string;
  rss_bytes: number;
  cpu_percent: number;
  cpu_time_seconds: number;
};

export type Insight = {
  level: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
};

export type MonitorState = {
  refresh_seconds: number;
  selected_tab: string;
};

export type Snapshot = {
  captured_at: string;
  workspace_id: string;
  install_root: string;
  machine: Machine;
  apps: AggregateRow[];
  workspaces: AggregateRow[];
  processes: ProcessRow[];
  service: Record<string, number>;
  insights: Insight[];
};

export type MonitorPayload = {
  state: MonitorState;
  snapshot: Snapshot;
};
