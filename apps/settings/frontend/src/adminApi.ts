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
  input_modalities?: string[];
  output_modalities?: string[];
  upstream_provider_options?: Array<{
    provider_id?: string;
    label?: string;
    tag?: string;
    quantization?: string;
    context_length?: number;
    max_completion_tokens?: number;
  }>;
  metadata?: Record<string, unknown>;
};

export type OpenRouterProviderRouting = {
  mode: 'auto' | 'prefer' | 'only' | 'ignore';
  provider_id?: string;
  allow_fallbacks?: boolean;
  require_parameters?: boolean;
  zdr?: boolean;
  sort?: '' | 'price' | 'throughput' | 'latency';
  data_collection?: '' | 'allow' | 'deny';
  quantizations?: string[];
};

export type ProviderModelSettings = {
  selected_model_id: string | null;
  selected_reasoning_effort: string | null;
  default_reasoning_effort?: string | null;
  available_models: ProviderModelOption[];
};

export type SpeechModelSettings = {
  audio_transcription_model_id: string | null;
  conversation_model_id: string | null;
  available_audio_transcription_models: ProviderModelOption[];
  available_conversation_models: ProviderModelOption[];
  available_models: ProviderModelOption[];
  endpoints?: {
    audio_transcription?: string | null;
    conversation?: string | null;
  };
};

export type SpeechProviderSelection = {
  workspace_id: string;
  profile: string;
  provider_id: string;
  selection_reason: string;
  updated_at: string;
  audio_transcription_model_id: string | null;
  conversation_model_id: string | null;
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

export type ProviderUsageWindow = {
  used_percent: number;
  limit_window_seconds: number | null;
  reset_after_seconds: number | null;
  reset_at_epoch_seconds: number | null;
};

export type ProviderUsageLimit = {
  limit_id: string;
  label: string;
  metered_feature: string | null;
  limit_reached: boolean;
  primary_window: ProviderUsageWindow | null;
  secondary_window: ProviderUsageWindow | null;
};

export type ProviderSubscriptionUsage = {
  provider_id: string;
  provider_label: string;
  available: boolean;
  fetched_at: string;
  plan_type: string | null;
  limits: ProviderUsageLimit[];
  unavailable_reason: string | null;
  credits_balance: number | null;
  credits_unlimited: boolean;
};

export type ProviderSubscriptionUsagePayload = {
  workspace_id: string;
  items: ProviderSubscriptionUsage[];
};

export type UsageTokenTotals = {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  estimated_cost_microusd: number | null;
};

export type UsageTimeSeriesItem = UsageTokenTotals & {
  bucket_start: string;
  bucket_end: string;
  sample_count: number;
};

export type UsageTimeSeriesProviderFacet = {
  provider_id: string;
  model_ids: string[];
};

export type UsageTimeSeriesPayload = {
  workspace_id: string;
  resolution: "hour" | "day";
  periods: number;
  provider_id: string | null;
  model_id: string | null;
  timezone: "UTC" | string;
  range_start: string;
  range_end: string;
  coverage_since: string | null;
  generated_at: string;
  facets?: {
    providers: UsageTimeSeriesProviderFacet[];
  };
  items: UsageTimeSeriesItem[];
  totals: UsageTokenTotals;
};

export type HostedProviderSelection = {
  workspace_id: string;
  profile: string;
  provider_id: string;
  selection_reason: string;
  updated_at: string;
  model_id: string | null;
  openrouter_provider_routing_by_model?: Record<string, OpenRouterProviderRouting>;
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

export type SpeechProviderStatus = {
  profile: string;
  active_provider: ProviderItem | null;
  credential_binding: {
    binding_id: string;
    provider_id: string;
    workspace_id: string | null;
    label: string | null;
    status: string;
    created_at: string;
    updated_at: string;
  } | null;
  selection?: SpeechProviderSelection | null;
  model_settings: SpeechModelSettings | null;
  available_providers: ProviderItem[];
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
  speech_stt?: SpeechProviderStatus | null;
  blocked_reason?: string | null;
  blocked_detail?: string | null;
  available_providers?: ProviderItem[];
};

export type AgenticRuntimePolicy = {
  max_steps_per_turn: number;
  max_tool_calls_per_turn: number;
  max_parallel_tool_calls: number;
  max_wall_time_seconds: number;
  max_tool_result_bytes: number;
  max_total_tool_result_bytes: number;
  max_input_tokens: number;
  max_output_tokens: number;
  max_estimated_cost_microusd: number | null;
  allowed_surface_kinds: string[];
  tool_handle_mode: 'none' | 'all_currently_authorized' | 'exact';
  allowed_tool_handles: string[];
  allow_filesystem_list: boolean;
  allow_filesystem_read: boolean;
  allow_filesystem_write: boolean;
  allow_shell: boolean;
  require_confirmation_for_mutating: boolean;
  require_confirmation_for_destructive: boolean;
  allowed_remote_data_classes: string[];
};

export type AgenticActorPolicy = {
  allow_workspace_admins: boolean;
  allowed_user_ids: string[];
  allowed_workspace_role_ids: string[];
  allowed_agent_type_ids: string[];
};

export type AgenticCertificate = {
  certificate_id: string;
  effective_status: string;
  expires_at: string;
  revoked_at: string | null;
  status_revision: number | null;
  certified_capabilities: Record<string, boolean | string[]>;
  tcb?: {
    manifest_id: string | null;
    manifest_version: string | null;
    structure_digest: string | null;
    live_digest: string | null;
  };
};

export type AgenticEffectiveCapabilities = {
  status: 'active' | 'blocked';
  reason_code: string | null;
  snapshot_digest: string;
  computed_at?: string;
  execution_mode?: 'sandbox' | 'full-access';
  capabilities: Record<string, boolean | string[]>;
  allowed_tool_handles?: string[];
  provider?: {
    provider_id?: string;
    model_id?: string;
    protocol?: string;
    certified_upstream_ids?: string[];
    effective_upstream_ids?: string[];
    health_status?: string;
    health_revision?: string;
  };
  data_policy?: {
    allowed_remote_data_classes?: string[];
    collection?: string;
    require_zdr?: boolean;
  };
  certificate?: {
    certificate_id?: string;
    suite_id?: string;
    suite_version?: string;
    expires_at?: string | null;
  };
  tcb?: { posture?: string; [key: string]: unknown };
};

export type AgenticCredentialBinding = {
  binding_id: string;
  provider_id: string;
  workspace_id: string | null;
  label: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type AgenticAdminItem = {
  definition_id: string;
  definition_revision: string;
  display_name: string;
  runtime_engine_id: string;
  model_provider_id: string;
  model_id: string;
  provider_protocol: string;
  provider_api_version: string | null;
  adapter_id: string;
  adapter_version_constraint: string;
  routing_constraint: {
    endpoint_id: string;
    allowed_upstream_ids: string[];
    allow_fallbacks: boolean;
    require_parameters: boolean;
    data_collection_policy: string;
    require_zdr: boolean;
    allowed_quantizations: string[];
  };
  profile_policy_ceiling: AgenticRuntimePolicy;
  rollout_status: string | null;
  certificate: AgenticCertificate | null;
  credential_bindings: AgenticCredentialBinding[];
  binding: {
    binding_id: string;
    revision: number;
    credential_binding_id: string | null;
    enabled: boolean;
    is_default: boolean;
    actor_policy: AgenticActorPolicy;
    workspace_policy_ceiling: AgenticRuntimePolicy;
    egress_policy_id: string;
    egress_policy_revision: string;
    created_at: string;
    updated_at: string;
  } | null;
  health: 'healthy' | 'blocked';
  blocked_reason: string | null;
  containment_status: 'GO' | 'NO-GO';
  containment_reason: string | null;
  binding_status: 'missing' | 'enabled' | 'disabled';
  profile_status: string;
  certificate_eligibility: string;
  effective_capabilities?: AgenticEffectiveCapabilities | null;
  upstream_provider_ids: string[];
  data_destination: {
    provider_id: string;
    endpoint_id: string;
    upstream_provider_ids: string[];
    display_label: string;
  };
  egress_policy: {
    policy_id: string;
    revision: string;
    allowed_remote_data_classes: string[];
  };
  data_policy: {
    collection: string;
    require_zdr: boolean;
    attestation_state: 'unavailable' | 'not_attested' | 'active' | 'revoked' | 'invalid';
    attestation?: {
      state: 'not_attested' | 'active' | 'revoked' | 'invalid';
      authoritative: boolean;
      declaration: string | null;
      scope: {
        type: 'workspace' | 'resource_prefixes';
        resource_prefixes: string[];
      } | null;
      revision: number | null;
      updated_at: string | null;
      attested_at?: string;
      revoked_at?: string | null;
    } | null;
  };
};

export type AgenticAdminPayload = {
  workspace_id: string;
  release_decision: 'GO' | 'NO-GO';
  items: AgenticAdminItem[];
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
  recovery_reason_code?: string | null;
  agentic_containment?: {
    status: 'GO' | 'NO-GO';
    reason_code: string | null;
  } | null;
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

export type RuntimeSessionInventoryPayload = {
  items: RuntimeSessionItem[];
  cleanup_allowed?: boolean;
  cleanup_scope?: 'none' | 'workspace' | 'server';
};

export type PlatformSettings = {
  user: SessionUser;
  workspace: WorkspaceItem;
  provider: ProviderStatus;
  runtime: RuntimeStatus;
  recovery: Record<string, unknown>;
  agentic_admin?: AgenticAdminPayload;
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

export function getProviderSubscriptionUsage(): Promise<ProviderSubscriptionUsagePayload> {
  return requestJson<ProviderSubscriptionUsagePayload>('/api/providers/usage');
}

export function getUsageTimeseries(
  resolution: "hour" | "day",
  periods: number,
  filters: { providerId?: string; modelId?: string } = {}
): Promise<UsageTimeSeriesPayload> {
  const query = new URLSearchParams({ resolution, periods: String(periods) });
  if (filters.providerId) query.set('provider_id', filters.providerId);
  if (filters.modelId) query.set('model_id', filters.modelId);
  return requestJson<UsageTimeSeriesPayload>(`/api/usage/timeseries?${query.toString()}`);
}

export function getRuntimeSessionInventory(): Promise<RuntimeSessionInventoryPayload> {
  return requestJson<RuntimeSessionInventoryPayload>('/api/settings/runtime-sessions');
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
  openrouter_provider_routing?: OpenRouterProviderRouting | null;
}): Promise<ProviderStatus> {
  return requestJson<ProviderStatus>('/api/providers/hosted/selection', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function configureSpeechProvider(payload: {
  provider_id: string;
  audio_transcription_model_id?: string | null;
  conversation_model_id?: string | null;
}): Promise<ProviderStatus> {
  return requestJson<ProviderStatus>('/api/providers/speech/selection', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function configureAgenticWorkspaceBinding(payload: {
  definition_id: string;
  definition_revision: string;
  binding_id?: string | null;
  expected_revision?: number | null;
  credential_binding_id?: string | null;
  enabled: boolean;
  is_default: boolean;
  actor_policy: AgenticActorPolicy;
  policy_patch: Record<string, unknown>;
}): Promise<{ binding_id: string; binding_revision: number; agentic_admin: AgenticAdminPayload }> {
  return requestJson('/api/providers/agentic/workspace-bindings', {
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
