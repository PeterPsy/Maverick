import type { AppDependenciesPayload, DependencyResolutionItem } from './types';

export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/agents/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Agents request failed');
  }
  return payload as T;
}

export async function callProviderBackend<T>(providerAppId: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Provider request failed');
  }
  return payload as T;
}

export async function getAppDependencies(consumerAppId = 'agents'): Promise<AppDependenciesPayload> {
  const params = new URLSearchParams({ consumer_app_id: consumerAppId });
  const response = await fetch(`/api/apps/dependencies?${params.toString()}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Dependency lookup failed');
  }
  return normalizeAppDependencies(payload, consumerAppId);
}

function normalizeAppDependencies(value: unknown, consumerAppId: string): AppDependenciesPayload {
  const payload = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return {
    workspace_id: stringField(payload.workspace_id, 'default'),
    consumer_app_id: stringField(payload.consumer_app_id, consumerAppId),
    status: stringField(payload.status, 'unknown'),
    dependencies: Array.isArray(payload.dependencies)
      ? payload.dependencies.map(normalizeDependencyResolution).filter((item) => item.alias)
      : []
  };
}

function normalizeDependencyResolution(value: unknown): DependencyResolutionItem {
  const payload = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return {
    alias: stringField(payload.alias),
    interface: stringField(payload.interface),
    version: stringField(payload.version),
    required: payload.required !== false,
    cardinality: payload.cardinality === 'many' ? 'many' : 'one',
    description: stringField(payload.description),
    status: stringField(payload.status, 'unknown'),
    candidates: Array.isArray(payload.candidates)
      ? payload.candidates.map((candidate) => {
        const item = candidate && typeof candidate === 'object' ? candidate as Record<string, unknown> : {};
        return {
          app_id: stringField(item.app_id),
          name: stringField(item.name),
          version: stringField(item.version),
          interface: stringField(item.interface),
          interface_version: stringField(item.interface_version),
          description: stringField(item.description),
          surfaces: stringArrayField(item.surfaces)
        };
      }).filter((candidate) => candidate.app_id)
      : [],
    selected_provider_app_ids: stringArrayField(payload.selected_provider_app_ids),
    stale_provider_app_ids: stringArrayField(payload.stale_provider_app_ids),
    blocked_reason: typeof payload.blocked_reason === 'string' ? payload.blocked_reason : null
  };
}

function stringField(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function stringArrayField(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}
