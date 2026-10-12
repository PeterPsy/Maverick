import { requestJson } from './adminApi';
import type { SettingsPageId } from './pages';

export const SETTINGS_RESOURCES = {
  registry: '/api/apps',
  context: '/api/settings/platform?section=context',
  models: '/api/settings/platform?section=models',
  voice: '/api/settings/platform?section=voice',
  'computer-use': '/api/settings/platform?section=computer-use',
  users: '/api/admin/users',
  workspaces: '/api/admin/workspaces',
  apps: '/api/admin/workspace-apps',
  persistence: '/api/admin/persistence',
  sessions: '/api/settings/runtime-sessions',
} as const;
export type SettingsResource = keyof typeof SETTINGS_RESOURCES;
export type ResourceState = { loaded: boolean; loading: boolean; error: string };

export function resourcesForPage(page: SettingsPageId): SettingsResource[] {
  if (page === 'users' || page === 'workspace-access') return ['users', 'workspaces'];
  if (page === 'workspace-apps') return ['context', 'workspaces', 'apps'];
  if (page === 'app-links') return ['context', 'apps'];
  if (page === 'sessions') return ['context', 'sessions'];
  if (page === 'usage' || page === 'learning') return ['context'];
  if (page === 'cache') return [];
  return [page];
}

export function createSettingsResources(context: {
  publish: (resource: SettingsResource, payload: unknown) => void;
  changed: (resource: SettingsResource) => void;
}) {
  const states = new Map<SettingsResource, ResourceState>();
  const pending = new Map<SettingsResource, { controller: AbortController; promise: Promise<void> }>();
  function state(resource: SettingsResource): ResourceState {
    if (!states.has(resource)) states.set(resource, { loaded: false, loading: false, error: '' });
    return states.get(resource)!;
  }
  function ensure(resource: SettingsResource, force = false): Promise<void> {
    if (!force && pending.has(resource)) return pending.get(resource)!.promise;
    if (!force && state(resource).loaded) return Promise.resolve();
    pending.get(resource)?.controller.abort();
    const controller = new AbortController();
    Object.assign(state(resource), { loading: true, error: '' });
    const started = performance.now();
    const promise = requestJson<unknown>(SETTINGS_RESOURCES[resource], { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        context.publish(resource, payload);
        state(resource).loaded = true;
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) state(resource).error = error instanceof Error ? error.message : 'Unable to load settings.';
      }).finally(() => {
        if (pending.get(resource)?.controller !== controller) return;
        pending.delete(resource);
        state(resource).loading = false;
        performance.clearMeasures(`settings.load.${resource}`);
        performance.measure(`settings.load.${resource}`, { start: started, end: performance.now() });
        context.changed(resource);
      });
    pending.set(resource, { controller, promise });
    context.changed(resource);
    return promise;
  }
  function reset() {
    pending.forEach(({ controller }) => controller.abort());
    pending.clear();
    states.clear();
  }
  function cancelExcept(resources: SettingsResource[]) {
    pending.forEach(({ controller }, resource) => {
      if (resources.includes(resource)) return;
      controller.abort();
      pending.delete(resource);
      state(resource).loading = false;
    });
  }
  return { state, ensure, reset, cancelExcept };
}
