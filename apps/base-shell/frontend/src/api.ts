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

export function listApps(): Promise<AppRegistryPayload> {
  return requestJson<AppRegistryPayload>("/api/apps");
}

export function getPlatformStatus(): Promise<PlatformStatus> {
  return requestJson<PlatformStatus>("/api/status");
}
