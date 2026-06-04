export type BackendStatus = {
  app_id?: string;
  workspace_id?: string | null;
  status?: string;
  [key: string]: unknown;
};

export type Site = {
  id: string;
  display_name: string;
  slug: string;
  status: string;
  source_provider: string;
  active_revision_id?: string | null;
  published_revision_id?: string | null;
  is_active?: boolean;
};

export type Page = {
  id: string;
  site_id: string;
  route: string;
  title: string;
  kind: string;
  status: string;
  source_files: string[];
};

export type Route = {
  id: string;
  site_id: string;
  route: string;
  page_id?: string;
  kind: string;
  status: string;
  source_files: string[];
};

export type Asset = {
  id: string;
  site_id: string;
  path: string;
  kind: string;
  status: string;
};

export type SitemapPayload = {
  site_id: string;
  items: Page[];
  routes: Route[];
  assets: Asset[];
};

export type WebsiteFile = {
  site_id: string;
  path: string;
  content: string;
  hash: string;
  revision_id?: string | null;
};

export type DiffFile = {
  path: string;
  status: string;
  patch: string;
};

export type StorageFile = {
  id?: string;
  file_id?: string;
  workspace_relative_path?: string;
  role?: string;
  relative_path?: string;
  name?: string;
  content_type?: string;
  sha256?: string;
};

type DependencyResolution = {
  alias: string;
  status: string;
  selected_provider_app_ids?: string[];
  blocked_reason?: string | null;
};

type AppDependencies = {
  status: string;
  dependencies: DependencyResolution[];
};

export async function callBackend<T = BackendStatus>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/website-studio/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(String(payload.detail || payload.error || `Backend request failed with ${response.status}`));
  }
  return response.json() as Promise<T>;
}

export async function callStorageProvider<T = { file?: StorageFile }>(alias: string, body: Record<string, unknown>): Promise<T> {
  const providerAppId = await selectedProviderAppId(alias);
  const response = await fetch(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(String(payload.detail || payload.error || `Storage request failed with ${response.status}`));
  }
  return response.json() as Promise<T>;
}

async function selectedProviderAppId(alias: string): Promise<string> {
  const params = new URLSearchParams({ consumer_app_id: 'website-studio' });
  const response = await fetch(`/api/apps/dependencies?${params.toString()}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(String(payload.detail || payload.error || `Dependency lookup failed with ${response.status}`));
  }
  const payload = await response.json() as AppDependencies;
  const dependency = payload.dependencies.find((item) => item.alias === alias);
  if (!dependency) {
    throw new Error(`Dependency alias ${alias} is not declared.`);
  }
  const providerAppId = dependency.selected_provider_app_ids?.[0] || '';
  if (!providerAppId) {
    throw new Error(dependency.blocked_reason || `Dependency alias ${alias} has no selected provider.`);
  }
  if (dependency.status !== 'resolved') {
    throw new Error(dependency.blocked_reason || `Dependency alias ${alias} is ${dependency.status || 'unresolved'}.`);
  }
  return providerAppId;
}
