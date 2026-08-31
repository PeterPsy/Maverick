import './styles.css';
import { createAdminUser, deleteAdminUser, installWorkspaceApp as installWorkspaceAppBinding, resetAdminUserPassword, setWorkspaceAppEnabled, uninstallWorkspaceApp as uninstallWorkspaceAppBinding, updateAdminUser, updateAdminUserMemberships } from './adminActions';
import { clearRuntimeSessions, getPlatformSettings, loadUsers, loadWorkspaces, loadWorkspaceApps, logout, requestJson } from './adminApi';
import type { AppDependenciesPayload, PlatformSettings, PersistenceStatus, RuntimeCleanupPayload, User, Workspace, WorkspaceApp } from './adminApi';
import { mergeRuntimeSessionInventory, requestRuntimeSessionInventoryQuiet } from './settingsRuntimeInventory';
import {
  createSettingsPanelState,
  settingsPanelHtml,
  syncSettingsPanelDraft,
  updateDraftModel,
  updateHostedDraftModel,
  updateHostedProviderRoutingDraft,
  updateSpeechAudioModel,
  updateSpeechConversationModel
} from './settingsPanel';
import {
  DEFAULT_SETTINGS_PAGE_ID,
  settingsPageById,
  settingsPageIdFromParams,
  type SettingsPage,
  type SettingsPageId
} from './pages';
import { settingsAppSkeletonHtml } from './appSkeleton';
import { createAppLinksController } from './appLinksController';
import { activeSettingsPageHtml } from './activePage';
import { bindSettingsEvents } from './bindEvents';
import { escapeHtml } from './html';
import { createPersistenceController } from './persistenceController';
import { persistenceMigrationModalHtml } from './persistencePage';
import { saveActiveProviderSettings, saveHostedProviderSettings, saveSpeechProviderSettings } from './providerSettingsActions';
import { mountUsageVisualizations, unmountUsageVisualizations } from './components/usageVisualizations';
import { createProviderUsageController } from './providerUsageController';
import { noticeHtml, type SettingsNotice } from './notice';
import { createAgenticBindingController } from './agenticBindingController';
import { createCacheDiagnosticsController } from './cacheDiagnosticsController';

let users: User[] = [];
let workspaces: Workspace[] = [];
let workspaceApps: WorkspaceApp[] = [];
let persistence: PersistenceStatus | null = null;
let platformSettings: PlatformSettings | null = null;
let settingsPanelState = createSettingsPanelState();
const initialNavigationParams = Object.fromEntries(new URLSearchParams(window.location.search).entries());
let selectedPageId: SettingsPageId = settingsPageIdFromParams(initialNavigationParams) || DEFAULT_SETTINGS_PAGE_ID;
let selectedUserId = userIdFromNavigationParams(initialNavigationParams);
let isLoading = true;
let pendingDeleteUserId = '';
let notice: SettingsNotice | null = null;
let lastPublishedPageId = '';
let lastPublishedUserId = '';
let runtimeInventoryWorkspaceId = '';
let isRuntimeInventoryLoading = false;

const persistenceController = createPersistenceController({
  getPersistence: () => persistence,
  render: () => render(),
  requestPersistenceStatusQuiet,
  setNotice: (nextNotice) => {
    notice = nextNotice;
  },
  setPersistence: (status) => {
    persistence = status;
  },
});

const appLinksController = createAppLinksController({
  publishChanged: publishAppDependenciesChanged,
  render: () => render(),
  setNotice: (nextNotice) => {
    notice = nextNotice;
  },
});

const providerUsageController = createProviderUsageController({
  getSettings: () => platformSettings,
  render: () => render(),
  state: settingsPanelState
});
const agenticBindingController = createAgenticBindingController({
  getSettings: () => platformSettings, render, state: settingsPanelState,
  setSettings: (settings, message) => { platformSettings = settings; notice = { tone: 'success', message }; }
});
const cacheDiagnosticsController = createCacheDiagnosticsController({
  render,
  setNotice: (nextNotice) => {
    notice = nextNotice;
  },
});

function selectedUser(): User | undefined { return users.find((user) => user.user_id === selectedUserId) || users[0]; }
function userIdFromNavigationParams(params: Record<string, unknown>): string {
  const directUserId = scalarParam(params.user_id) || scalarParam(params.selected_user_id) || scalarParam(params.id);
  if (directUserId) {
    return directUserId;
  }
  const appPage = scalarParam(params.app_page);
  const userPageMatch = /^users\/([^/?#]+)$/.exec(appPage);
  if (!userPageMatch?.[1]) {
    return '';
  }
  try {
    return decodeURIComponent(userPageMatch[1]);
  } catch {
    return userPageMatch[1];
  }
}

function scalarParam(value: unknown): string { return typeof value === 'string' ? value.trim() : ''; }

function applyNavigationParams(params: Record<string, unknown>) {
  const pageId = settingsPageIdFromParams(params);
  const userId = userIdFromNavigationParams(params);
  let changed = false;
  if (pageId && pageId !== selectedPageId) {
    selectedPageId = pageId;
    changed = true;
  }
  if (userId && userId !== selectedUserId) {
    selectedUserId = userId;
    pendingDeleteUserId = '';
    changed = true;
  }
  if (!changed) {
    return;
  }
  if (users.length || isLoading) {
    render();
  }
  if (pageId === 'app-links') {
    void ensureAppLinksLoaded();
  }
  if (pageId === 'platform-settings') {
    void ensureRuntimeInventoryLoaded();
    void providerUsageController.ensureLoaded();
  }
  if (pageId === 'cache') {
    void cacheDiagnosticsController.ensureLoaded();
  }
}

function publishSelectedPage(page: SettingsPage) {
  if (page.id === lastPublishedPageId || window.parent === window) {
    return;
  }
  lastPublishedPageId = page.id;
  window.parent.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'settings',
      selection: { page_id: page.id }
    },
    window.location.origin
  );
}

function publishSelectedUser(user: User | undefined) {
  if (!user || user.user_id === lastPublishedUserId || window.parent === window) {
    return;
  }
  lastPublishedUserId = user.user_id;
  window.parent.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'settings',
      selection: { user_id: user.user_id }
    },
    window.location.origin
  );
}

function publishUserDataChanged() {
  if (window.parent === window) {
    return;
  }
  window.parent.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: 'settings',
      resource: 'users'
    },
    window.location.origin
  );
}

async function requestPersistenceStatus(): Promise<PersistenceStatus | null> {
  try {
    return await requestJson<PersistenceStatus>('/api/admin/persistence');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Persistence API unavailable';
    notice = { tone: 'error', message };
    return null;
  }
}

async function requestPersistenceStatusQuiet(): Promise<PersistenceStatus | null> {
  try {
    return await requestJson<PersistenceStatus>('/api/admin/persistence');
  } catch {
    return null;
  }
}

async function requestPlatformSettingsQuiet(): Promise<PlatformSettings | null> {
  try {
    return await getPlatformSettings();
  } catch {
    return null;
  }
}

async function refresh() {
  isLoading = true;
  render();
  try {
    const [usersPayload, workspacesPayload, workspaceAppsPayload, persistencePayload, settingsPayload] = await Promise.all([
      loadUsers(),
      loadWorkspaces(),
      loadWorkspaceApps(),
      requestPersistenceStatus(),
      requestPlatformSettingsQuiet()
    ]);
    const previousWorkspaceId = platformSettings?.workspace.workspace_id || '';
    const nextWorkspaceId = settingsPayload?.workspace.workspace_id || '';
    users = usersPayload;
    workspaces = workspacesPayload;
    workspaceApps = workspaceAppsPayload;
    persistence = persistencePayload;
    platformSettings = settingsPayload;
    if (previousWorkspaceId !== nextWorkspaceId) {
      appLinksController.reset();
      runtimeInventoryWorkspaceId = '';
      providerUsageController.reset();
    }
    syncSettingsPanelDraft(settingsPanelState, platformSettings);
    if (!selectedUserId || !users.some((user) => user.user_id === selectedUserId)) {
      selectedUserId = users[0]?.user_id || '';
    }
  } finally {
    isLoading = false;
  }
  render();
  if (selectedPageId === 'app-links') {
    void ensureAppLinksLoaded();
  }
  if (selectedPageId === 'platform-settings') {
    void ensureRuntimeInventoryLoaded();
    void providerUsageController.ensureLoaded();
  }
  if (selectedPageId === 'cache') {
    void cacheDiagnosticsController.ensureLoaded();
  }
}

async function ensureAppLinksLoaded(force = false) {
  const workspaceId = platformSettings?.workspace.workspace_id || '';
  await appLinksController.ensureLoaded(workspaceId, workspaceApps, force);
}

async function ensureRuntimeInventoryLoaded(force = false) {
  const workspaceId = platformSettings?.workspace.workspace_id || '';
  if (!workspaceId || isRuntimeInventoryLoading || (!force && runtimeInventoryWorkspaceId === workspaceId)) {
    return;
  }
  isRuntimeInventoryLoading = true;
  try {
    const inventory = await requestRuntimeSessionInventoryQuiet();
    if (!inventory || platformSettings?.workspace.workspace_id !== workspaceId) {
      return;
    }
    platformSettings = mergeRuntimeSessionInventory(platformSettings, inventory);
    runtimeInventoryWorkspaceId = workspaceId;
    syncSettingsPanelDraft(settingsPanelState, platformSettings);
    render();
  } finally {
    isRuntimeInventoryLoading = false;
  }
}

async function createUser(form: HTMLFormElement) {
  const data = new FormData(form);
  const created = await createAdminUser({
    username: String(data.get('username') || ''),
    password: String(data.get('password') || ''),
    display_name: String(data.get('display_name') || ''),
    email: String(data.get('email') || ''),
    platform_role: String(data.get('platform_role') || 'member')
  });
  selectedUserId = created.user_id;
  form.reset();
  await refresh();
  publishUserDataChanged();
}

async function updateSelectedUser(form: HTMLFormElement, user: User) {
  const data = new FormData(form);
  await updateAdminUser(user.user_id, {
    display_name: String(data.get('display_name') || ''),
    email: String(data.get('email') || ''),
    platform_role: String(data.get('platform_role') || 'member'),
    account_type: String(data.get('account_type') || 'standard'),
    is_active: data.get('is_active') === 'on'
  });
  await refresh();
  publishUserDataChanged();
}

async function resetSelectedUserPassword(form: HTMLFormElement, user: User) {
  const data = new FormData(form);
  const password = String(data.get('password') || '');
  const confirmation = String(data.get('password_confirmation') || '');
  if (password !== confirmation) {
    throw new Error('Passwords do not match');
  }
  await resetAdminUserPassword(user.user_id, password);
  form.reset();
  notice = { tone: 'success', message: 'Password updated.' };
  render();
}

async function deleteSelectedUser(user: User) {
  const label = user.display_name || user.username;
  if (pendingDeleteUserId !== user.user_id) {
    pendingDeleteUserId = user.user_id;
    notice = {
      tone: 'info',
      message: `Press Delete user again to confirm permanent removal of ${label}.`
    };
    render();
    return;
  }
  await deleteAdminUser(user.user_id);
  selectedUserId = '';
  pendingDeleteUserId = '';
  notice = { tone: 'success', message: `${label} deleted.` };
  await refresh();
  publishUserDataChanged();
}

async function updateMemberships(user: User) {
  const memberships = workspaces
    .map((workspace) => {
      const checkbox = document.querySelector<HTMLInputElement>(`[data-workspace-enabled="${workspace.workspace_id}"]`);
      const role = document.querySelector<HTMLSelectElement>(`[data-workspace-role="${workspace.workspace_id}"]`);
      return checkbox?.checked ? { workspace_id: workspace.workspace_id, role: role?.value || 'member' } : null;
    })
    .filter((membership): membership is { role: string; workspace_id: string } => Boolean(membership));
  await updateAdminUserMemberships(user.user_id, memberships);
  await refresh();
  publishUserDataChanged();
}

async function installWorkspaceApp(app: WorkspaceApp) {
  await installWorkspaceAppBinding(app);
  appLinksController.invalidate();
  await refresh();
}

async function setWorkspaceAppStatus(app: WorkspaceApp, enabled: boolean) {
  await setWorkspaceAppEnabled(app, enabled);
  appLinksController.invalidate();
  await refresh();
}

async function uninstallWorkspaceApp(app: WorkspaceApp) {
  await uninstallWorkspaceAppBinding(app);
  appLinksController.invalidate();
  await refresh();
}

async function saveDependencySelection(consumerAppId: string, alias: string, providerAppIds: string[]) {
  await appLinksController.saveDependencySelection(consumerAppId, alias, providerAppIds);
}

async function clearRuntimeSessionsFromPanel(sessionIds?: string[]) {
  const scopedIds = (sessionIds || []).filter(Boolean);
  settingsPanelState.cleanupError = '';
  if (scopedIds.length) {
    scopedIds.forEach((sessionId) => settingsPanelState.cleaningSessionIds.add(sessionId));
  } else {
    settingsPanelState.clearingAllRuntime = true;
  }
  render();
  try {
    const payload = await clearRuntimeSessions(scopedIds.length ? scopedIds : undefined);
    publishRuntimeCleanupChanged(payload);
    platformSettings = mergeRuntimeSessionInventory(await getPlatformSettings(), payload);
    runtimeInventoryWorkspaceId = platformSettings.workspace.workspace_id;
    syncSettingsPanelDraft(settingsPanelState, platformSettings);
    notice = {
      tone: 'success',
      message: scopedIds.length ? 'Runtime session cleaned.' : 'Runtime sessions cleaned.'
    };
  } catch (error) {
    settingsPanelState.cleanupError = error instanceof Error ? error.message : 'Unable to clean runtime sessions.';
  } finally {
    scopedIds.forEach((sessionId) => settingsPanelState.cleaningSessionIds.delete(sessionId));
    settingsPanelState.clearingAllRuntime = false;
    render();
  }
}

function publishRuntimeCleanupChanged(payload: RuntimeCleanupPayload) {
  if (payload.deleted_threads <= 0 || window.parent === window) {
    return;
  }
  window.parent.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: 'chat',
      resource: 'threads'
    },
    window.location.origin
  );
  payload.deleted_thread_ids.forEach((threadId) => {
    window.parent.postMessage(
      {
        type: 'maverick.app.data-changed',
        owner_app_id: 'chat',
        resource: 'threads',
        deleted_thread_id: threadId
      },
      window.location.origin
    );
  });
}

function publishAppDependenciesChanged(consumerAppId: string, dependencies: AppDependenciesPayload) {
  if (window.parent === window) {
    return;
  }
  window.parent.postMessage(
    {
      type: 'maverick.app.dependencies-changed',
      app_id: consumerAppId,
      status: dependencies.status
    },
    window.location.origin
  );
}

async function logoutFromSettings() {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'maverick.shell.logout' }, window.location.origin);
    return;
  }
  await logout();
  window.location.href = '/';
}

function platformSettingsPageHtml() {
  return settingsPanelHtml(platformSettings, settingsPanelState);
}

function render() {
  const root = document.getElementById('app');
  const user = isLoading ? undefined : selectedUser();
  const page = settingsPageById(selectedPageId);
  if (!root) return;
  unmountUsageVisualizations();
  root.innerHTML = `<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${
          isLoading
            ? settingsAppSkeletonHtml(page)
            : `<header class="detail-header">
          <div class="detail-title-block">
            <h2>${escapeHtml(page.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${escapeHtml(page.summary)}</p>
          </div>
        </header>
        ${noticeHtml(notice)}
        ${activeSettingsPageHtml({
          appLinksController,
          cacheDiagnosticsController,
          page,
          pendingDeleteUserId,
          persistenceController,
          platformSettingsHtml: platformSettingsPageHtml,
          selectedUser: user,
          users,
          workspaceApps,
          workspaces,
        })}`
        }
      </div>
    </section>
    ${persistenceMigrationModalHtml(persistenceController.viewState())}
  </main>`;
  bindEvents();
  mountUsageVisualizations({ history: settingsPanelState.usageHistory, filters: settingsPanelState.usageHistoryFilters, isLoading: settingsPanelState.isLoadingUsageHistory, onFiltersChange: providerUsageController.updateUsageHistoryFilters, settings: platformSettings });
  publishSelectedPage(page);
  if (!isLoading) {
    publishSelectedUser(user);
  }
}

function bindEvents() {
  bindSettingsEvents({
    clearRuntimeSessionsFromPanel,
    cacheDiagnosticsController,
    createUser,
    deleteSelectedUser,
    dismissNotice: () => {
      notice = null;
      render();
    },
    installWorkspaceApp,
    logoutFromSettings,
    onHostedProviderRoutingChanged: (modelId, field, value) => {
      updateHostedProviderRoutingDraft(settingsPanelState, platformSettings, modelId, field, value);
      render();
    },
    saveAgenticBindingFromPanel: agenticBindingController.save,
    onProviderModelChanged: (modelId) => {
      updateDraftModel(settingsPanelState, modelId);
      render();
    },
    onSpeechAudioModelChanged: (modelId) => {
      updateSpeechAudioModel(settingsPanelState, modelId);
      render();
    },
    onSpeechConversationModelChanged: (modelId) => {
      updateSpeechConversationModel(settingsPanelState, modelId);
      render();
    },
    persistenceController,
    refreshProviderUsageFromPanel: providerUsageController.refresh,
    render,
    resetSelectedUserPassword,
    saveDependencySelection,
    saveHostedProviderSettingsFromPanel: (modelId) => {
      if (modelId) {
        updateHostedDraftModel(settingsPanelState, platformSettings, modelId);
      }
      return saveHostedProviderSettings(providerSettingsActionContext());
    },
    saveProviderSettingsFromPanel: () => saveActiveProviderSettings(providerSettingsActionContext()),
    saveSpeechProviderSettingsFromPanel: () => saveSpeechProviderSettings(providerSettingsActionContext()),
    selectedUser,
    selectUser: (userId) => {
      selectedUserId = userId;
      pendingDeleteUserId = '';
      render();
    },
    setWorkspaceAppStatus,
    showError,
    uninstallWorkspaceApp,
    updateMemberships,
    updateSelectedUser,
    workspaceApps: () => workspaceApps,
    appDependencies: () => appLinksController.viewState().dependencies,
  });
}

function providerSettingsActionContext() {
  return {
    render,
    setNotice: (nextNotice: { tone: 'info' | 'success' | 'error'; message: string }) => {
      notice = nextNotice;
    },
    setSettings: (nextSettings: PlatformSettings) => {
      platformSettings = nextSettings;
    },
    settings: platformSettings,
    state: settingsPanelState
  };
}

function showError(error: unknown) {
  const message = error instanceof Error ? error.message : 'Unexpected error';
  notice = { tone: 'error', message };
  render();
}

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
    return;
  }
  const payload = event.data as { app_id?: string; params?: Record<string, unknown>; type?: string };
  if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'settings')) {
    applyNavigationParams(payload.params || {});
  }
});

window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'settings' }, window.location.origin);

refresh().catch(showError);
