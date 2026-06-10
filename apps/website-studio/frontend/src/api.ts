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

export type RuntimeSummary = {
  runtime_kind?: string;
  runtime_status?: string;
  missing_requirements?: string[];
  latest_build?: { id?: string; status?: string; logs_summary?: string; [key: string]: unknown } | null;
  latest_preview?: {
    id?: string;
    site_id?: string;
    route?: string;
    page_id?: string;
    build_id?: string;
    runtime_kind?: string;
    status?: string;
    preview_url?: string;
    warnings?: string[];
    missing_requirements?: string[];
    [key: string]: unknown;
  } | null;
};

export type SiteStatusPayload = {
  site: Site;
  page_count: number;
  route_count: number;
  asset_count: number;
  changed_files_count: number;
  active_revision_id?: string | null;
  published_revision_id?: string | null;
  runtime?: RuntimeSummary;
  runtime_kind?: string;
  runtime_status?: string;
  missing_requirements?: string[];
  latest_build_id?: string;
  latest_preview_id?: string;
};

export type BootstrapPayload = {
  sites: Site[];
  active_site_id: string;
  persisted_active_site_id: string;
  sitemap: SitemapPayload;
  latest_preview?: RuntimeSummary['latest_preview'] | null;
};

export type ChangeRecord = {
  id?: string;
  status?: string;
  mode?: string;
  diff_summary?: string;
  environment_id?: string;
  build_id?: string;
  source_ref?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  path?: string;
};

export type ChangeHistoryPayload = {
  site_id: string;
  base_revision_id?: string | null;
  published_revision_id?: string | null;
  working_diff: ChangeRecord[];
  publish_requests: ChangeRecord[];
  approval_events: ChangeRecord[];
  builds: ChangeRecord[];
  deployments: ChangeRecord[];
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

export type PreviewPayload = {
  preview_id: string;
  site_id: string;
  environment_id: string;
  route: string;
  page_id?: string;
  route_id?: string;
  runtime_kind: string;
  runtime_status: string;
  preview_url: string;
  build_id: string;
  missing_requirements: string[];
  warnings: string[];
  html: string;
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
