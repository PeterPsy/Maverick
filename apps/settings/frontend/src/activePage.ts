import type { User, Workspace, WorkspaceApp } from './adminApi';
import type { createAppLinksController } from './appLinksController';
import { appLinksPageHtml } from './appLinksPage';
import type { createCacheDiagnosticsController } from './cacheDiagnosticsController';
import { cacheDiagnosticsPageHtml } from './cacheDiagnosticsPage';
import type { SettingsPage } from './pages';
import type { createPersistenceController } from './persistenceController';
import { persistencePageHtml } from './persistencePage';
import { usersPageHtml, workspaceAccessPageHtml } from './userPages';
import { workspaceAppsPageHtml } from './workspaceAppsPage';

export function activeSettingsPageHtml(context: {
  appLinksController: ReturnType<typeof createAppLinksController>;
  cacheDiagnosticsController: ReturnType<typeof createCacheDiagnosticsController>;
  page: SettingsPage;
  pendingDeleteUserId: string;
  persistenceController: ReturnType<typeof createPersistenceController>;
  platformSettingsHtml: () => string;
  selectedUser: User | undefined;
  users: User[];
  workspaceApps: WorkspaceApp[];
  workspaces: Workspace[];
}): string {
  const { page, selectedUser } = context;
  if (page.id === 'users') {
    return usersPageHtml({ pendingDeleteUserId: context.pendingDeleteUserId, selectedUser, users: context.users });
  }
  if (page.id === 'workspace-access') {
    return workspaceAccessPageHtml({ selectedUser, users: context.users, workspaces: context.workspaces });
  }
  if (page.id === 'workspace-apps') {
    return workspaceAppsPageHtml({ workspaceApps: context.workspaceApps, workspaces: context.workspaces });
  }
  if (page.id === 'app-links') {
    const state = context.appLinksController.viewState();
    return appLinksPageHtml({
      appRegistry: state.appRegistry,
      dependencies: state.dependencies,
      error: state.error,
      isLoading: state.isLoading,
      loadErrors: state.loadErrors,
      savingKeys: state.savingKeys,
      workspaceApps: context.workspaceApps,
    });
  }
  if (page.id === 'platform-settings') return context.platformSettingsHtml();
  if (page.id === 'cache') return cacheDiagnosticsPageHtml(context.cacheDiagnosticsController.viewState());
  return persistencePageHtml(context.persistenceController.viewState());
}
