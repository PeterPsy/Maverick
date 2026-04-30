export type AppLogo = {
  kind: "glyph" | "image";
  value: string;
};

export type AppRegistryItem = {
  app_id: string;
  name: string;
  version: string;
  description: string;
  publisher: string;
  status: string;
  distribution_mode: string;
  source_access: string;
  views: string[];
  provides: AppInterfaceDeclaration[];
  requires: AppRequiredInterfaceDeclaration[];
  logo: AppLogo | null;
  frontend_mount: string;
  backend_mount: string;
};

export type AppInterfaceDeclaration = {
  interface: string;
  version: string;
  description: string;
  surfaces: string[];
};

export type AppRequiredInterfaceDeclaration = {
  alias: string;
  interface: string;
  version: string;
  required: boolean;
  cardinality: "one" | "many";
  description: string;
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

export type DependencyResolutionItem = AppRequiredInterfaceDeclaration & {
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

export type AppRegistryPayload = {
  items: AppRegistryItem[];
};

export type PlatformStatus = {
  status: string;
  workspace_id: string;
  apps: AppRegistryItem[];
};

export type SessionUser = {
  user_id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  account_type: string;
  platform_role: string;
};

export type SessionPayload =
  | {
      authenticated: false;
    }
  | {
      authenticated: true;
      user: SessionUser;
      workspace_id: string;
      expires_at: string;
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

export type WorkspacesPayload = {
  items: WorkspaceItem[];
  active_workspace_id: string;
};

export type ProviderItem = {
  provider_id: string;
  label: string;
  description: string;
  status: string;
  default_model_family: string | null;
  model_options: ProviderModelOption[];
  capabilities: Record<string, boolean>;
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
  blocked_reason?: string | null;
  blocked_detail?: string | null;
  available_providers?: ProviderItem[];
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

export type RuntimeSessionItem = {
  session_id: string;
  workspace_id: string;
  workspace_name?: string;
  agent_id: string;
  source_app_id?: string | null;
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
  cleanup_scope?: "none" | "workspace" | "server";
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

export type WidgetRegistryItem = {
  owner_app_id: string;
  widget_id: string;
  host: string;
  content_kinds: string[];
  frontend_mount: string;
  actions: Record<string, boolean>;
};

export type WidgetRegistryPayload = {
  items: WidgetRegistryItem[];
};

export type WidgetContextPayload = {
  context_token: string;
  context: Record<string, unknown>;
};

export type PinnedAppsPayload = {
  pinned_apps: string[];
};

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });
  if (!response.ok) {
    throw new Error(`Request failed ${response.status}: ${path}`);
  }
  return (await response.json()) as T;
}

function stringField(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function stringArrayField(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeProvidedInterface(value: unknown): AppInterfaceDeclaration {
  const item = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    interface: stringField(item.interface),
    version: stringField(item.version, "1"),
    description: stringField(item.description),
    surfaces: stringArrayField(item.surfaces),
  };
}

function normalizeRequiredInterface(value: unknown): AppRequiredInterfaceDeclaration {
  const item = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    alias: stringField(item.alias),
    interface: stringField(item.interface),
    version: stringField(item.version, "^1"),
    required: item.required === true,
    cardinality: item.cardinality === "many" ? "many" : "one",
    description: stringField(item.description),
  };
}

function normalizeDependencyCandidate(value: unknown): DependencyProviderCandidate {
  const item = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    app_id: stringField(item.app_id),
    name: stringField(item.name),
    version: stringField(item.version, "0.0.0"),
    interface: stringField(item.interface),
    interface_version: stringField(item.interface_version, "1"),
    description: stringField(item.description),
    surfaces: stringArrayField(item.surfaces),
  };
}

function normalizeDependencyResolution(value: unknown): DependencyResolutionItem {
  const item = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    ...normalizeRequiredInterface(item),
    status: stringField(item.status, "unknown"),
    candidates: Array.isArray(item.candidates) ? item.candidates.map(normalizeDependencyCandidate).filter((candidate) => candidate.app_id) : [],
    selected_provider_app_ids: stringArrayField(item.selected_provider_app_ids),
    stale_provider_app_ids: stringArrayField(item.stale_provider_app_ids),
    blocked_reason: item.blocked_reason === null ? null : stringField(item.blocked_reason) || null,
  };
}

function normalizeLogo(value: unknown): AppLogo | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Partial<AppLogo>;
  const kind = candidate.kind === "image" || candidate.kind === "glyph" ? candidate.kind : null;
  return kind && typeof candidate.value === "string" ? { kind, value: candidate.value } : null;
}

export function normalizeAppRegistryItem(value: unknown): AppRegistryItem {
  const item = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const appId = stringField(item.app_id);
  const name = stringField(item.name, appId || "Unnamed app");
  return {
    app_id: appId,
    name,
    version: stringField(item.version, "0.0.0"),
    description: stringField(item.description),
    publisher: stringField(item.publisher),
    status: stringField(item.status, "unknown"),
    distribution_mode: stringField(item.distribution_mode, "unknown"),
    source_access: stringField(item.source_access, "unknown"),
    views: stringArrayField(item.views),
    provides: Array.isArray(item.provides) ? item.provides.map(normalizeProvidedInterface).filter((entry) => entry.interface) : [],
    requires: Array.isArray(item.requires) ? item.requires.map(normalizeRequiredInterface).filter((entry) => entry.alias) : [],
    logo: normalizeLogo(item.logo),
    frontend_mount: stringField(item.frontend_mount),
    backend_mount: stringField(item.backend_mount),
  };
}

export function getAppDependencies(consumerAppId: string): Promise<AppDependenciesPayload> {
  const params = new URLSearchParams({ consumer_app_id: consumerAppId });
  return requestJson<unknown>(`/api/apps/dependencies?${params.toString()}`).then((value) => {
    const payload = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
    return {
      workspace_id: stringField(payload.workspace_id, "default"),
      consumer_app_id: stringField(payload.consumer_app_id, consumerAppId),
      status: stringField(payload.status, "unknown"),
      dependencies: Array.isArray(payload.dependencies)
        ? payload.dependencies.map(normalizeDependencyResolution).filter((item) => item.alias)
        : [],
    };
  });
}

export function saveAppDependencySelection(
  consumerAppId: string,
  alias: string,
  providerAppIds: string[],
): Promise<AppDependenciesPayload> {
  return requestJson<unknown>("/api/apps/dependencies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      consumer_app_id: consumerAppId,
      alias,
      provider_app_ids: providerAppIds,
    }),
  }).then((value) => {
    const payload = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
    return {
      workspace_id: stringField(payload.workspace_id, "default"),
      consumer_app_id: stringField(payload.consumer_app_id, consumerAppId),
      status: stringField(payload.status, "unknown"),
      dependencies: Array.isArray(payload.dependencies)
        ? payload.dependencies.map(normalizeDependencyResolution).filter((item) => item.alias)
        : [],
    };
  });
}

export function normalizeAppRegistryPayload(value: unknown): AppRegistryPayload {
  const payload = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeAppRegistryItem).filter((item) => item.app_id) : [];
  return { items };
}

export function listApps(): Promise<AppRegistryPayload> {
  return requestJson<unknown>("/api/apps").then(normalizeAppRegistryPayload);
}

export function listPinnedApps(): Promise<PinnedAppsPayload> {
  return requestJson<unknown>("/api/apps/app-store/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "pinned_apps.list" }),
  }).then((value) => {
    const payload = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
    return { pinned_apps: stringArrayField(payload.pinned_apps).map((item) => item.trim()).filter(Boolean) };
  });
}

export function getPlatformStatus(): Promise<PlatformStatus> {
  return requestJson<unknown>("/api/status").then((value) => {
    const payload = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
    return {
      status: stringField(payload.status, "unknown"),
      workspace_id: stringField(payload.workspace_id, "default"),
      apps: normalizeAppRegistryPayload({ items: payload.apps }).items,
    };
  });
}

export function getSession(): Promise<SessionPayload> {
  return requestJson<SessionPayload>("/api/session");
}

export function login(username: string, password: string): Promise<SessionPayload> {
  return requestJson<SessionPayload>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function logout(): Promise<SessionPayload> {
  return requestJson<SessionPayload>("/api/auth/logout", { method: "POST" });
}

export function listWorkspaces(): Promise<WorkspacesPayload> {
  return requestJson<WorkspacesPayload>("/api/workspaces");
}

export function createWorkspace(name: string): Promise<WorkspaceItem> {
  return requestJson<WorkspaceItem>("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function switchWorkspace(workspace_id: string): Promise<{ active_workspace_id: string }> {
  return requestJson<{ active_workspace_id: string }>("/api/workspaces/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_id }),
  });
}

export function getActiveProvider(): Promise<ProviderStatus> {
  return requestJson<ProviderStatus>("/api/providers/active");
}

export function configureActiveProvider(payload: {
  provider_id: string;
  model_id?: string | null;
  model_reasoning_effort?: string | null;
}): Promise<ProviderStatus> {
  return requestJson<ProviderStatus>("/api/providers/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getRuntimeStatus(): Promise<RuntimeStatus> {
  return requestJson<RuntimeStatus>("/api/runtime/status");
}

export function getPlatformSettings(): Promise<PlatformSettings> {
  return requestJson<PlatformSettings>("/api/settings/platform");
}

export function listRuntimeSessions(): Promise<{ items: RuntimeSessionItem[] }> {
  return requestJson<{ items: RuntimeSessionItem[] }>("/api/settings/runtime-sessions");
}

export function clearRuntimeSessions(session_ids?: string[], reason = "base_shell_settings_cleared"): Promise<RuntimeCleanupPayload> {
  return requestJson<RuntimeCleanupPayload>("/api/settings/runtime-sessions/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_ids, reason }),
  });
}

export function listWidgets(host: string, contentKind: string): Promise<WidgetRegistryPayload> {
  const query = new URLSearchParams({ host, content_kind: contentKind });
  return requestJson<WidgetRegistryPayload>(`/api/apps/widgets?${query.toString()}`);
}

export function createWidgetContext(payload: {
  host_app_id: string;
  owner_app_id: string;
  widget_id: string;
  message_id: string;
  content: Record<string, unknown>;
}): Promise<WidgetContextPayload> {
  return requestJson<WidgetContextPayload>("/api/apps/widgets/context", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
