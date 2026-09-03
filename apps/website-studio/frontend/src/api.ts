import {
  createRequestFingerprint,
  readThroughParentDataCache,
  type ParentDataCacheReadResult
} from '@maverick/pwa-cache';

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

export type SnapshotVersions = Record<'workspace_version' | 'project_version' | 'source_version' | 'navigation_version' | 'working_state_version' | 'preview_version' | 'activity_version' | 'settings_version', string>;

export type WorkspaceSnapshot = {
  schema: 'workspace_snapshot.v1';
  versions: SnapshotVersions;
  revision: string;
  not_modified?: boolean;
  workspace?: { projects: Site[]; active_project_id: string; persisted_active_project_id: string };
  project?: null | {
    site: Site;
    navigation: { site_id: string; site: Site; pages: Page[]; routes: Route[]; inventory_summary: { page_count: number; route_count: number; asset_count: number } };
    working_state: { changed_files_count: number };
    activity: { latest_build?: ChangeRecord | null; latest_publish_request?: ChangeRecord | null };
    latest_preview?: RuntimeSummary['latest_preview'] | null;
  };
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

export async function callBackend<T = BackendStatus>(body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api/apps/website-studio/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    const transport = new Error('Website Studio backend transport failed.', { cause: error });
    transport.name = 'MaverickTransportError';
    throw transport;
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: unknown; error?: unknown };
    throw new WebsiteHttpError(
      String(payload.detail || payload.error || `Backend request failed with ${response.status}`),
      response.status,
      parseRetryAfter(response.headers.get('retry-after'))
    );
  }
  try {
    return await response.json() as T;
  } catch (error) {
    throw new TypeError('Website Studio returned an invalid JSON response.', { cause: error });
  }
}

export class WebsiteHttpError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfterMs: number | null) {
    super(message);
    this.name = 'MaverickHttpError';
  }
}

type SnapshotRequest = {
  promise: Promise<WorkspaceSnapshot>;
  revalidated: Promise<WorkspaceSnapshot | null>;
  signal?: AbortSignal;
};
const snapshotRequests = new Map<string, SnapshotRequest>();

export function cachedWorkspaceSnapshot(
  siteId = '',
  route = '/',
  options: { revalidate?: boolean; signal?: AbortSignal } = {}
): { fresh: Promise<WorkspaceSnapshot>; revalidated: Promise<WorkspaceSnapshot | null> } {
  const key = `${siteId || 'active'}::${route || '/'}`;
  const legacyStorageKey = `website-studio:snapshot:${key}`;
  let migrationPayload: WorkspaceSnapshot | null = null;
  try {
    const value = sessionStorage.getItem(legacyStorageKey);
    migrationPayload = value ? sanitizeLegacyWorkspaceSnapshot(JSON.parse(value)) : null;
  } catch { /* storage can be unavailable in sandboxed widgets */ }
  const existing = snapshotRequests.get(key);
  if (existing && ((!options.signal && !existing.signal) || existing.signal === options.signal)) {
    return { fresh: existing.promise, revalidated: existing.revalidated };
  }
  const migrationSeed = migrationPayload
    ? { payload: migrationPayload, revision: migrationPayload.revision }
    : undefined;
  let resolveRevalidated!: (value: WorkspaceSnapshot | null) => void;
  let rejectRevalidated!: (error: unknown) => void;
  const revalidated = new Promise<WorkspaceSnapshot | null>((resolve, reject) => {
    resolveRevalidated = resolve;
    rejectRevalidated = reject;
  });
  void revalidated.catch(() => undefined);
  let fresh: Promise<WorkspaceSnapshot>;
  const loader = async ({ knownRevision, signal }: { knownRevision?: string; signal?: AbortSignal }) => {
    const payload = await callBackend<WorkspaceSnapshot>({
      action: 'workspace_snapshot',
      site_id: siteId || undefined,
      route: route || undefined,
      known_revision: options.revalidate === false ? undefined : knownRevision
    }, signal);
    if (payload.not_modified) {
      if (!knownRevision) throw new TypeError('Website Studio returned not_modified without a known revision.');
      if (payload.revision !== knownRevision) throw new TypeError('Website Studio returned not_modified for a different revision.');
      return { kind: 'not_modified', revision: knownRevision } as const;
    }
    const sanitized = sanitizeWorkspaceSnapshot(payload);
    if (!sanitized) throw new TypeError('Website Studio returned an invalid workspace snapshot.');
    return { kind: 'value', payload: sanitized, revision: sanitized.revision } as const;
  };
  fresh = createRequestFingerprint(JSON.stringify({ route: route || '/', site_id: siteId || 'active' }))
    .then((entityId) => readThroughParentDataCache<WorkspaceSnapshot>({
      appId: 'website-studio',
      entityId,
      migrationSeed,
      resource: 'site-snapshots',
      schemaRevision: 'website-studio.site-snapshots.v2'
    }, loader, {
      sanitize: sanitizeWorkspaceSnapshot,
      signal: options.signal
    }))
    .catch(async (error): Promise<ParentDataCacheReadResult<WorkspaceSnapshot>> => {
      if (error instanceof Error && error.message.startsWith('SHA-256 is unavailable')) {
        const direct = await loader({ signal: options.signal });
        if (direct.kind === 'not_modified') throw new TypeError('Website Studio direct reads require a value.');
        return {
          brokered: false,
          freshness: 'fresh' as const,
          migrationCommitted: false,
          payload: direct.payload,
          revision: direct.revision,
          source: 'network' as const
        };
      }
      throw error;
    })
    .then((result) => {
    if (migrationSeed && result.brokered && result.migrationCommitted) {
      try { sessionStorage.removeItem(legacyStorageKey); } catch { /* best effort */ }
    }
    if (result.revalidation) {
      void result.revalidation.then((next) => {
        resolveRevalidated(next.changed ? next.payload : null);
      }, rejectRevalidated);
    } else {
      resolveRevalidated(null);
    }
    return result.payload;
  }).catch((error) => {
    rejectRevalidated(error);
    throw error;
  }).finally(() => {
    if (snapshotRequests.get(key)?.promise === fresh) snapshotRequests.delete(key);
  });
  snapshotRequests.set(key, { promise: fresh, revalidated, signal: options.signal });
  return { fresh, revalidated };
}

export function invalidateWorkspaceSnapshots(resources: string[] = []) {
  if (!resources.length || resources.some((resource) => [
    'records', 'source', 'working-state', 'navigation', 'preview', 'activity', 'settings', 'view-selection'
  ].includes(resource))) {
    snapshotRequests.clear();
    try {
      for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
        const key = sessionStorage.key(index);
        if (key?.startsWith('website-studio:snapshot:')) sessionStorage.removeItem(key);
      }
    } catch { /* storage can be unavailable in sandboxed widgets */ }
  }
}

export function sanitizeWorkspaceSnapshot(value: unknown): WorkspaceSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const payload = value as Partial<WorkspaceSnapshot>;
  if (payload.schema !== 'workspace_snapshot.v1'
      || !payload.versions
      || typeof payload.versions !== 'object'
      || !SNAPSHOT_VERSION_KEYS.every((key) => typeof payload.versions?.[key] === 'string')
      || !validSnapshotRevision(payload.revision)) return null;
  try {
    const cloned = JSON.parse(JSON.stringify(payload, sanitizeSnapshotField)) as WorkspaceSnapshot;
    if (cloned.not_modified === true
        || (cloned.workspace === undefined && cloned.project === undefined)
        || (cloned.workspace !== undefined && !validSnapshotWorkspace(cloned.workspace))
        || (cloned.project !== undefined && cloned.project !== null && !validSnapshotProject(cloned.project))) {
      return null;
    }
    return cloned;
  } catch {
    return null;
  }
}

function sanitizeSnapshotField(key: string, item: unknown): unknown {
  const normalized = key.replace(/[^A-Za-z0-9]/gu, '').toLowerCase();
  if (['authorization', 'credential', 'credentials', 'downloadurl', 'localpath', 'password', 'signedurl', 'streamurl', 'token'].includes(normalized)
      || normalized.endsWith('token')
      || normalized.endsWith('secret')) return undefined;
  if (typeof item === 'string'
      && (/^blob\s*:/iu.test(item)
        || /[?&](?:sig|signature|x-amz-signature|x-goog-signature)=/iu.test(item))) return undefined;
  return item;
}

function validSnapshotWorkspace(value: unknown): boolean {
  if (!isSnapshotRecord(value)) return false;
  const workspace = value as { projects?: unknown; active_project_id?: unknown; persisted_active_project_id?: unknown };
  return Array.isArray(workspace.projects)
    && workspace.projects.every((site) => isSnapshotRecord(site) && typeof site.id === 'string')
    && typeof workspace.active_project_id === 'string'
    && typeof workspace.persisted_active_project_id === 'string';
}

function validSnapshotProject(value: unknown): boolean {
  if (!isSnapshotRecord(value)) return false;
  const project = value as { site?: unknown; navigation?: unknown; working_state?: unknown; activity?: unknown };
  if (!isSnapshotRecord(project.site)
      || typeof project.site.id !== 'string'
      || !isSnapshotRecord(project.navigation)
      || !Array.isArray(project.navigation.pages)
      || !Array.isArray(project.navigation.routes)
      || !isSnapshotRecord(project.working_state)
      || !isSnapshotRecord(project.activity)) return false;
  return project.navigation.pages.every((page) => isSnapshotRecord(page) && typeof page.id === 'string')
    && project.navigation.routes.every((route) => isSnapshotRecord(route) && typeof route.id === 'string');
}

function isSnapshotRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function sanitizeLegacyWorkspaceSnapshot(value: unknown): WorkspaceSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const payload = value as Partial<WorkspaceSnapshot>;
  if (!payload.versions || typeof payload.versions !== 'object'
      || !SNAPSHOT_VERSION_KEYS.every((key) => typeof payload.versions?.[key] === 'string')) return null;
  return sanitizeWorkspaceSnapshot({
    ...payload,
    revision: validSnapshotRevision(payload.revision)
      ? payload.revision
      : legacySnapshotRevision(payload.versions as SnapshotVersions)
  });
}

function validSnapshotRevision(value: unknown): value is string {
  return typeof value === 'string'
    && (/^[a-f0-9]{64}$/u.test(value) || /^legacy:[a-f0-9]{16}$/u.test(value));
}

const SNAPSHOT_VERSION_KEYS: Array<keyof SnapshotVersions> = [
  'workspace_version', 'project_version', 'source_version', 'navigation_version',
  'working_state_version', 'preview_version', 'activity_version', 'settings_version'
];

function legacySnapshotRevision(versions: SnapshotVersions): string {
  const serialized = SNAPSHOT_VERSION_KEYS.map((key) => `${key}:${versions[key]}`).join('|');
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < serialized.length; index += 1) {
    const code = serialized.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
  }
  return `legacy:${(first >>> 0).toString(16).padStart(8, '0')}${(second >>> 0).toString(16).padStart(8, '0')}`;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1_000, 60_000);
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, Math.min(timestamp - Date.now(), 60_000)) : null;
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
