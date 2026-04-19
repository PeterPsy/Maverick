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

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
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
