import { currentStorageAppId } from './api';
import type { AppBootstrapPayload } from './types';

const BOOTSTRAP_CACHE_VERSION = 1;
const FORBIDDEN_SESSION_STORAGE_KEYS = new Set([
  'appsecretrequest',
  'authorization',
  'credential',
  'credentials',
  'downloadurl',
  'localpath',
  'password',
  'path',
  'signedurl',
  'streamurl'
]);

type BootstrapCacheScope = {
  workspaceId: string;
  appId: string;
  storageAppId: string;
};

function bootstrapCacheKey(scope: BootstrapCacheScope) {
  return `fitness-coach:bootstrap:${scope.workspaceId}:${scope.appId}:${scope.storageAppId}`;
}

export function bootstrapCacheScopeFromLocation(requireWorkspace: boolean): BootstrapCacheScope | null {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  const workspaceId = params.get('workspace_id') || params.get('workspace') || '';
  const appId = params.get('app_id') || 'fitness-coach';
  const storageAppId = currentStorageAppId();
  if (requireWorkspace && !workspaceId) return null;
  return { workspaceId, appId, storageAppId };
}

function bootstrapCacheScopeFromPayload(payload: AppBootstrapPayload): BootstrapCacheScope | null {
  if (!payload.workspace_id) return null;
  return {
    workspaceId: payload.workspace_id,
    appId: payload.app_id || 'fitness-coach',
    storageAppId: currentStorageAppId()
  };
}

export function readBootstrapCache(): AppBootstrapPayload | null {
  if (typeof window === 'undefined') return null;
  const scope = bootstrapCacheScopeFromLocation(true);
  if (!scope) return null;
  const key = bootstrapCacheKey(scope);
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { version?: number; payload?: unknown };
    if (parsed.version !== BOOTSTRAP_CACHE_VERSION || !parsed.payload || typeof parsed.payload !== 'object') {
      return null;
    }
    const payload = sanitizeLegacyBootstrapReadModel(parsed.payload);
    if (!payload) return null;
    if (payload.workspace_id !== scope.workspaceId || (payload.app_id || 'fitness-coach') !== scope.appId) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

export function removeBootstrapCache(payload: AppBootstrapPayload) {
  const scope = bootstrapCacheScopeFromPayload(payload);
  if (!scope) return;
  try {
    window.sessionStorage.removeItem(bootstrapCacheKey(scope));
  } catch {
    // A verified parent migration remains valid if legacy cleanup is blocked.
  }
}

function sanitizeBootstrapForSessionStorage(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sanitizeBootstrapForSessionStorage(item));
  if (!value || typeof value !== 'object') return value;
  const next: Record<string, unknown> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
    const normalized = key.replace(/[^A-Za-z0-9]/gu, '').toLowerCase();
    if (FORBIDDEN_SESSION_STORAGE_KEYS.has(normalized)
        || normalized.endsWith('token')
        || normalized.endsWith('secret')) return;
    if (typeof item === 'string'
        && (/^blob\s*:/iu.test(item)
          || /[?&](?:sig|signature|x-amz-signature|x-goog-signature)=/iu.test(item))) return;
    next[key] = sanitizeBootstrapForSessionStorage(item);
  });
  return next;
}

export function sanitizeBootstrapReadModel(value: unknown): AppBootstrapPayload | null {
  return sanitizeBootstrap(value, false);
}

function sanitizeLegacyBootstrapReadModel(value: unknown): AppBootstrapPayload | null {
  return sanitizeBootstrap(value, true);
}

function sanitizeBootstrap(value: unknown, allowMissingSchema: boolean): AppBootstrapPayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const payload = value as Partial<AppBootstrapPayload>;
  if ((payload.schema !== 'fitness-coach.bootstrap.v1'
        && !(allowMissingSchema && payload.schema === undefined))
      || typeof payload.workspace_id !== 'string'
      || payload.workspace_id.length > 256
      || typeof payload.app_id !== 'string'
      || payload.app_id.length > 256
      || typeof payload.state_version !== 'string'
      || !payload.state_version
      || payload.state_version.length > 256
      || !Array.isArray(payload.workouts)
      || !Array.isArray(payload.workout_summaries)
      || !Array.isArray(payload.exercises)
      || !Array.isArray(payload.tags)
      || !Array.isArray(payload.runs)
      || !payload.view_state || typeof payload.view_state !== 'object'
      || !payload.workouts.every(hasBoundedId)
      || !payload.workout_summaries.every(hasBoundedId)
      || !payload.exercises.every(hasBoundedId)
      || !payload.runs.every(hasBoundedId)
      || !payload.tags.every((tag) => typeof tag === 'string')
      || (payload.selected_workout !== null && !hasBoundedId(payload.selected_workout))
      || !validViewState(payload.view_state)) return null;
  try {
    const sanitized = sanitizeBootstrapForSessionStorage(payload) as AppBootstrapPayload;
    sanitized.schema = 'fitness-coach.bootstrap.v1';
    delete sanitized.not_modified;
    return sanitized;
  } catch {
    return null;
  }
}

function hasBoundedId(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const id = (value as { id?: unknown }).id;
  return typeof id === 'string' && id.length > 0 && id.length <= 256;
}

function validViewState(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const state = value as { selected_workout_id?: unknown; setup_tab?: unknown; sidebar_query?: unknown };
  return (state.selected_workout_id === null || typeof state.selected_workout_id === 'string')
    && (state.setup_tab === 'workout-settings' || state.setup_tab === 'exercise-library')
    && typeof state.sidebar_query === 'string';
}
