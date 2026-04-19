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
  logo: AppLogo | null;
  frontend_mount: string;
  backend_mount: string;
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

export type ProviderStatus = {
  workspace_id: string;
  active_provider: {
    provider_id: string;
    label: string;
    description: string;
    status: string;
    default_model_family: string | null;
    capabilities: Record<string, boolean>;
  };
  selection: Record<string, unknown> | null;
};

export type RuntimeStatus = ProviderStatus & {
  sessions: Array<{
    session_id: string;
    agent_id: string;
    status: string;
    effective_mode: string;
    last_progress_at: string | null;
  }>;
};

export type PlatformSettings = {
  user: SessionUser;
  workspace: WorkspaceItem;
  provider: ProviderStatus;
  runtime: RuntimeStatus;
  recovery: Record<string, unknown>;
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
    logo: normalizeLogo(item.logo),
    frontend_mount: stringField(item.frontend_mount),
    backend_mount: stringField(item.backend_mount),
  };
}

export function normalizeAppRegistryPayload(value: unknown): AppRegistryPayload {
  const payload = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeAppRegistryItem).filter((item) => item.app_id) : [];
  return { items };
}

export function listApps(): Promise<AppRegistryPayload> {
  return requestJson<unknown>("/api/apps").then(normalizeAppRegistryPayload);
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

export function getRuntimeStatus(): Promise<RuntimeStatus> {
  return requestJson<RuntimeStatus>("/api/runtime/status");
}

export function getPlatformSettings(): Promise<PlatformSettings> {
  return requestJson<PlatformSettings>("/api/settings/platform");
}
