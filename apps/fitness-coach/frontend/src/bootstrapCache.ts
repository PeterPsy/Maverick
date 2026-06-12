import { currentStorageAppId } from './api';
import type { AppBootstrapPayload } from './types';

const BOOTSTRAP_CACHE_VERSION = 1;
const FORBIDDEN_SESSION_STORAGE_KEYS = new Set(['stream_url', 'download_url', '_app_secret_request', 'token', 'access_token', 'refresh_token', 'local_path', 'path']);

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
    const payload = parsed.payload as Partial<AppBootstrapPayload>;
    if (payload.workspace_id !== scope.workspaceId || (payload.app_id || 'fitness-coach') !== scope.appId) {
      return null;
    }
    return payload as AppBootstrapPayload;
  } catch {
    return null;
  }
}

export function writeBootstrapCache(payload: AppBootstrapPayload) {
  if (typeof window === 'undefined') return;
  const scope = bootstrapCacheScopeFromPayload(payload);
  if (!scope) return;
  const key = bootstrapCacheKey(scope);
  try {
    window.sessionStorage.setItem(
      key,
      JSON.stringify({
        version: BOOTSTRAP_CACHE_VERSION,
        cached_at: new Date().toISOString(),
        payload: sanitizeBootstrapForSessionStorage(payload)
      })
    );
  } catch {
    // Cache is best-effort and must never block the app.
  }
}

function sanitizeBootstrapForSessionStorage(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sanitizeBootstrapForSessionStorage(item));
  if (!value || typeof value !== 'object') return value;
  const next: Record<string, unknown> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
    if (FORBIDDEN_SESSION_STORAGE_KEYS.has(key)) return;
    next[key] = sanitizeBootstrapForSessionStorage(item);
  });
  return next;
}
