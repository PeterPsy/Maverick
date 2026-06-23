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

export type AppLogo = {
  kind: 'glyph' | 'image';
  value: string;
};

export type AppRegistryItem = {
  app_id: string;
  name: string;
  views: string[];
  logo: AppLogo | null;
};

export type DependencyProviderCandidate = {
  app_id: string;
  name: string;
  version: string;
  interface: string;
  interface_version: string;
  description: string;
  surfaces: string[];
};

export type DependencyResolutionItem = {
  alias: string;
  interface: string;
  version: string;
  required: boolean;
  cardinality: 'one' | 'many';
  description: string;
  status: string;
  candidates: DependencyProviderCandidate[];
  selected_provider_app_ids: string[];
  stale_provider_app_ids: string[];
  blocked_reason: string | null;
};

export type AppDependenciesPayload = {
  workspace_id: string;
  consumer_app_id: string;
  status: string;
  dependencies: DependencyResolutionItem[];
};

export type PersistenceAdapter = {
  kind: 'json' | 'mongo';
  json_root: string;
  mongo_uri: string | null;
  mongo_database: string;
  mongo_username?: string | null;
  mongo_password_ref?: string | null;
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
  target_collections?: { name: string; count: number }[];
  same_adapter?: boolean;
  restart_required_for_cutover: boolean;
  active_adapter_changed?: boolean;
  env_file?: string | { path: string; updated: boolean; missing: boolean };
  backend_restart?: { restarted: boolean; scheduled: boolean; detail: string; method: string; healthy: boolean };
  source_cleanup?: { scheduled: boolean; mode: string };
};

export type MigrationPlan = MigrationResult & {
  status: 'dry_run';
  target_collections: { name: string; count: number }[];
  same_adapter: boolean;
  env_file: string;
};

export type MigrationTargetPayload = {
  kind: 'json' | 'mongo';
  json_root: string;
  mongodb_uri: string;
  mongodb_database: string;
  mongodb_username?: string;
  mongodb_password_ref?: string;
};

export type SessionUser = {
  user_id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  account_type: string;
  platform_role: string;
};

export type WorkspaceItem = {
  workspace_id: string;
  name: string;
  description: string | null;
  status: string;
  governance: Record<string, boolean>;
  quota: Record<string, unknown>;
  is_active: boolean;
};

export type ProviderReasoningOption = {
  effort: string;
  label: string;
  description: string | null;
};

export type ProviderModelOption = {
  model_id: string;
  label: string;
  description: string | null;
  default_reasoning_effort: string | null;
  supported_reasoning_efforts: ProviderReasoningOption[];
};

export type ProviderModelSettings = {
  selected_model_id: string | null;
  selected_reasoning_effort: string | null;
  available_models: ProviderModelOption[];
};

export type ProviderItem = {
  provider_id: string;
  label: string;
  description: string;
  kind?: string;
  provider_role?: string;
  status: string;
  default_model_family: string | null;
  model_options: ProviderModelOption[];
  capabilities: Record<string, boolean>;
};

export type HostedProviderSelection = {
  workspace_id: string;
  profile: string;
  provider_id: string;
  selection_reason: string;
  updated_at: string;
  model_id: string | null;
};

export type HostedTextProviderStatus = {
  profile: string;
  active_provider: ProviderItem | null;
  selection: HostedProviderSelection | null;
  model_settings: ProviderModelSettings | null;
  available_providers: ProviderItem[];
  route_preview?: {
    selected_provider_id: string | null;
    selected_model_id_or_voice_id: string | null;
    selected_runtime_engine_id: string | null;
    execution_path: string | null;
    reason_codes: string[];
  } | null;
};

export type ProviderStatus = {
  workspace_id: string;
  configured?: boolean;
  active_provider: ProviderItem | null;
  selection: {
    workspace_id: string;
    provider_id: string;
    binding_id: string | null;
    selection_scope: string;
    selection_reason: string;
    updated_at: string;
    model_id: string | null;
    model_reasoning_effort: string | null;
  } | null;
  model_settings: ProviderModelSettings | null;
  hosted_text?: HostedTextProviderStatus | null;
  blocked_reason?: string | null;
  blocked_detail?: string | null;
  available_providers?: ProviderItem[];
};

export type RuntimeSessionItem = {
  session_id: string;
  workspace_id: string;
  workspace_name?: string;
  agent_id: string;
  source_app_id?: string | null;
  skill_catalog_app_id?: string | null;
  provider_id?: string | null;
  provider_thread_id?: string | null;
  status: string;
  requested_mode?: string | null;
  effective_mode: string;
  started_at?: string | null;
  updated_at?: string | null;
  ended_at?: string | null;
  last_progress_at: string | null;
};

export type RuntimeStatus = ProviderStatus & {
  sessions: RuntimeSessionItem[];
  all_sessions?: RuntimeSessionItem[];
  cleanup_allowed?: boolean;
  cleanup_scope?: 'none' | 'workspace' | 'server';
};

export type RuntimeCleanupPayload = {
  cleared_sessions: number;
  terminated_processes: number;
  cancelled_turns: number;
  deleted_threads: number;
  deleted_thread_ids: string[];
  runtime_roots_deleted: number;
  deleted: Record<string, number>;
  results: Array<{
    session_id: string;
    workspace_id: string;
    deleted: Record<string, number>;
    deleted_threads: number;
    runtime_root_deleted: boolean;
  }>;
  sessions: RuntimeSessionItem[];
};

export type PlatformSettings = {
  user: SessionUser;
  workspace: WorkspaceItem;
  provider: ProviderStatus;
  runtime: RuntimeStatus;
  recovery: Record<string, unknown>;
};

export type SessionPayload = {
  authenticated: boolean;
  user: SessionUser | null;
  workspace_id: string;
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

function stringField(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function stringArrayField(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function normalizeLogo(value: unknown): AppLogo | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const candidate = value as Partial<AppLogo>;
  const kind = candidate.kind === 'image' || candidate.kind === 'glyph' ? candidate.kind : null;
  return kind && typeof candidate.value === 'string' ? { kind, value: candidate.value } : null;
}

function normalizeAppRegistryItem(value: unknown): AppRegistryItem {
  const item = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const appId = stringField(item.app_id);
  return {
    app_id: appId,
    name: stringField(item.name, appId || 'Unnamed app'),
    views: stringArrayField(item.views),
    logo: normalizeLogo(item.logo)
  };
}

export async function loadAppRegistry(): Promise<AppRegistryItem[]> {
  const payload = await requestJson<{ items?: unknown[] }>('/api/apps');
  return (payload.items || []).map(normalizeAppRegistryItem).filter((item) => item.app_id);
}

export function getAppDependencies(consumerAppId: string): Promise<AppDependenciesPayload> {
  const params = new URLSearchParams({ consumer_app_id: consumerAppId });
  return requestJson<AppDependenciesPayload>(`/api/apps/dependencies?${params.toString()}`);
}

export function saveAppDependencySelection(
  consumerAppId: string,
  alias: string,
  providerAppIds: string[]
): Promise<AppDependenciesPayload> {
  return requestJson<AppDependenciesPayload>('/api/apps/dependencies', {
    method: 'POST',
    body: JSON.stringify({
      consumer_app_id: consumerAppId,
      alias,
      provider_app_ids: providerAppIds
    })
  });
}

export function getPlatformSettings(): Promise<PlatformSettings> {
  return requestJson<PlatformSettings>('/api/settings/platform');
}

export function configureActiveProvider(payload: {
  provider_id: string;
  model_id?: string | null;
  model_reasoning_effort?: string | null;
}): Promise<ProviderStatus> {
  return requestJson<ProviderStatus>('/api/providers/active', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function configureHostedProvider(payload: {
  provider_id: string;
  model_id?: string | null;
}): Promise<ProviderStatus> {
  return requestJson<ProviderStatus>('/api/providers/hosted/selection', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function clearRuntimeSessions(session_ids?: string[], reason = 'settings_runtime_sessions_cleared'): Promise<RuntimeCleanupPayload> {
  return requestJson<RuntimeCleanupPayload>('/api/settings/runtime-sessions/clear', {
    method: 'POST',
    body: JSON.stringify({ session_ids, reason })
  });
}

export function logout(): Promise<SessionPayload> {
  return requestJson<SessionPayload>('/api/auth/logout', { method: 'POST' });
}

export function dryRunPersistenceMigration(payload: MigrationTargetPayload): Promise<MigrationPlan> {
  return requestJson<MigrationPlan>('/api/admin/persistence/migrations/dry-run', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function applyPersistenceMigration(payload: MigrationTargetPayload & { delete_source: boolean; restart_backend: boolean }): Promise<MigrationResult> {
  return requestJson<MigrationResult>('/api/admin/persistence/migrations/apply', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}
