import { getPlatformSettings, loadUsers, loadWorkspaces, loadWorkspaceApps, requestJson,
  type PlatformSettings, type User, type Workspace, type WorkspaceApp, type PersistenceStatus } from './adminApi';

export async function requestPersistenceStatusQuiet(): Promise<PersistenceStatus | null> {
  try { return await requestJson<PersistenceStatus>('/api/admin/persistence'); }
  catch { return null; }
}

export async function loadSettingsBootstrap(context: {
  isCurrent: () => boolean;
  publishPlatform: (settings: PlatformSettings | null) => void;
  publishInventory: (inventory: { users: User[]; workspaces: Workspace[]; workspaceApps: WorkspaceApp[];
    persistence: PersistenceStatus | null }) => void;
  reportError: (error: unknown) => void;
}) {
  // Attach rejection handlers immediately; a slow inventory must not delay Settings.
  const inventory = Promise.allSettled([loadUsers(), loadWorkspaces(), loadWorkspaceApps(),
    requestJson<PersistenceStatus>('/api/admin/persistence')]);
  try {
    const settings = await getPlatformSettings();
    if (context.isCurrent()) context.publishPlatform(settings);
  } catch (error) {
    if (context.isCurrent()) {
      context.publishPlatform(null);
      context.reportError(error);
    }
  }
  const [users, workspaces, workspaceApps, persistence] = await inventory;
  if (!context.isCurrent()) return;
  context.publishInventory({ users: users.status === 'fulfilled' ? users.value : [],
    workspaces: workspaces.status === 'fulfilled' ? workspaces.value : [],
    workspaceApps: workspaceApps.status === 'fulfilled' ? workspaceApps.value : [],
    persistence: persistence.status === 'fulfilled' ? persistence.value : null });
  for (const result of [users, workspaces, workspaceApps, persistence]) {
    if (result.status === 'rejected') context.reportError(result.reason);
  }
}
