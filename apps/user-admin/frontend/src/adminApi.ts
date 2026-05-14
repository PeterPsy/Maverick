export type Membership = {
  workspace_id: string;
  role: 'admin' | 'member';
  status: string;
};

export type User = {
  user_id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  platform_role: 'admin' | 'member';
  account_type: string;
  is_active: boolean;
  memberships: Membership[];
};

export type Workspace = {
  workspace_id: string;
  name: string;
  status: string;
};

export type WorkspaceApp = {
  workspace_id: string;
  workspace_name: string;
  app_id: string;
  name: string;
  description: string;
  version: string;
  source_id: string;
  installed: boolean;
  status: 'uninstalled' | 'installed' | 'enabled' | 'disabled' | 'failed' | 'updating' | 'rolled_back';
};

export type PersistenceAdapter = {
  kind: 'json' | 'mongo';
  json_root: string;
  mongo_uri: string | null;
  mongo_database: string;
};

export type PersistenceStatus = {
  active_adapter: PersistenceAdapter;
  collections: { name: string; count: number }[];
  restart_required_for_cutover: boolean;
};

export type MigrationResult = {
  status: string;
  source_adapter: PersistenceAdapter;
  target_adapter: PersistenceAdapter;
  collections: { name: string; count: number }[];
  restart_required_for_cutover: boolean;
  active_adapter_changed?: boolean;
  env_file?: { path: string; updated: boolean; missing: boolean };
  backend_restart?: { restarted: boolean; scheduled: boolean; detail: string; method: string; healthy: boolean };
  source_cleanup?: { scheduled: boolean; mode: string };
};

export async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed ${response.status}`);
  }
  return payload as T;
}

export async function loadUsers(): Promise<User[]> {
  const payload = await requestJson<{ items: User[] }>('/api/admin/users');
  return payload.items;
}

export async function loadWorkspaces(): Promise<Workspace[]> {
  const payload = await requestJson<{ items: Workspace[] }>('/api/admin/workspaces');
  return payload.items;
}

export async function loadWorkspaceApps(): Promise<WorkspaceApp[]> {
  const payload = await requestJson<{ items: WorkspaceApp[] }>('/api/admin/workspace-apps');
  return payload.items;
}
