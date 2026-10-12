import { setWorkspaceAppEnabled } from './adminActions';
import type { WorkspaceApp } from './adminApi';

export function createWorkspaceAppController(context: {
  render: () => void;
  updated: (app: WorkspaceApp, enabled: boolean) => void;
}) {
  let generation = 0;
  const pending = new Map<string, boolean>();
  const key = (app: WorkspaceApp) => `${app.workspace_id}:${app.app_id}`;
  return {
    reset: () => { generation++; pending.clear(); },
    savingKeys: () => new Set(pending.keys()),
    apps: (apps: WorkspaceApp[]) => apps.map(app => pending.has(key(app))
      ? { ...app, status: pending.get(key(app)) ? 'enabled' as const : 'disabled' as const } : app),
    setEnabled: async (app: WorkspaceApp, enabled: boolean) => {
      const request = generation;
      const appKey = key(app);
      if (pending.has(appKey)) return;
      pending.set(appKey, enabled);
      context.render();
      try {
        await setWorkspaceAppEnabled(app, enabled);
        if (request === generation) context.updated(app, enabled);
      } catch (error) {
        if (request === generation) throw error;
      } finally {
        if (request === generation) { pending.delete(appKey); context.render(); }
      }
    }
  };
}
