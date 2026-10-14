import './styles.css';
import { createInstallationPage } from './installationPage';
import './styles/learning.css';
import './styles/learning-tickets.css';
import './styles/speech-settings.css';
import './styles/navigation.css';
import { readLoopinoAppFrameContext } from '@loopino/pwa-cache';
import { createSpeechSynthesisController } from './speechSynthesisSettings';
import { createComputerUseController } from './computerUseSettings';
import { requestPersistenceStatusQuiet } from './persistenceStatus';
import { createSettingsResources, resourcesForPage } from './settingsResources';
import { mergeSettingsSnapshot } from './settingsSnapshot';
import { patchSettingsDom, rememberSettingsDrafts, clearSettingsDrafts, clearSettingsDomCache } from './settingsDom';
import { beginSettingsBindings, bindControl } from './controlBindings';
import { confirmSettingsAction, syncSettingsModalFocus } from './settingsDialogs';
import { createSessionsView, scopedSessions, sessionsPageHtml } from './sessionsPage';
import { usagePageHtml } from './usagePage';
import { createLearningController } from './learningController';
import { learningPageHtml } from './learningPage';
import { bindSettingsHostEvents, settingsHostVisible } from './settingsHostEvents';
import { createAdminUser, deleteAdminUser, installWorkspaceApp as installWorkspaceAppBinding, resetAdminUserPassword, uninstallWorkspaceApp as uninstallWorkspaceAppBinding, updateAdminUser, updateAdminUserMemberships } from './adminActions';
import { clearRuntimeSessions, logout, requestJson } from './adminApi';
import type { AppDependenciesPayload, PlatformSettings, PersistenceStatus, RuntimeCleanupPayload, User, Workspace, WorkspaceApp } from './adminApi';
import { mergeRuntimeSessionInventory } from './settingsRuntimeInventory';
import { createSettingsPanelState, syncSettingsPanelDraft, updateHostedDraftModel, updateHostedProviderRoutingDraft, updateSpeechAudioModel, updateSpeechConversationModel } from './settingsDrafts';
import { settingsPanelHtml } from './settingsPanel';
import {
  DEFAULT_SETTINGS_PAGE_ID,
  settingsPageById,
  settingsPageIdFromParams,
  settingsPageDomKey,
  type SettingsPage,
  type SettingsPageId
} from './pages';
import { settingsAppSkeletonHtml } from './appSkeleton';
import { createAppLinksController } from './appLinksController';
import { createWorkspaceAppController } from './workspaceAppController';
import { activeSettingsPageHtml } from './activePage';
import { bindSettingsEvents } from './bindEvents';
import { escapeHtml } from './html';
import { createPersistenceController } from './persistenceController';
import { persistenceMigrationModalHtml } from './persistencePage';
import { saveHostedProviderSettings, saveSpeechProviderSettings } from './providerSettingsActions';
import { createProviderUsageController } from './providerUsageController';
import { noticeHtml, type SettingsNotice } from './notice';
import { createAgenticBindingController } from './agenticBindingController';
import { createCacheDiagnosticsController } from './cacheDiagnosticsController';

let usageVisualizations: typeof import('./components/usageVisualizations') | null = null;
let usageVisualizationsRequest: Promise<unknown> | null = null;
const installationPage = createInstallationPage();
let users: User[] = [];
let iconRegistry: import('./adminApi').AppRegistryItem[] = [];
let iconWorkspaceId = '';
let workspaces: Workspace[] = [];
let workspaceApps: WorkspaceApp[] = [];
let persistence: PersistenceStatus | null = null;
let platformSettings: PlatformSettings | null = null;
let settingsWorkspaceId = readLoopinoAppFrameContext()?.workspaceId || '';
let settingsPanelState = createSettingsPanelState();
const initialNavigationParams = Object.fromEntries(new URLSearchParams(window.location.search).entries());
let selectedPageId: SettingsPageId = settingsPageIdFromParams(initialNavigationParams) || DEFAULT_SETTINGS_PAGE_ID;
let selectedUserId = userIdFromNavigationParams(initialNavigationParams);
let isLoading = true;
let notice: SettingsNotice | null = null;
let lastPublishedPageId = '';
let lastPublishedUserId = '';
const sessionsView = createSessionsView();
let renderedPageId = '';
let focusSetting = '';
let draftsRemembered = false;

const speechSynthesisController = createSpeechSynthesisController({
  state: settingsPanelState.speechSynthesis, render,
  notify: (message) => { notice = { tone: 'success', message }; }
});

const computerUseController = createComputerUseController({
  state: settingsPanelState.computerUse, getSettings: () => platformSettings, render,
  setSelection: (selection) => { if (platformSettings) platformSettings = { ...platformSettings, computer_use: selection }; },
  notify: (message) => { notice = { tone: 'success', message }; }
});

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
const workspaceAppController = createWorkspaceAppController({
  render,
  updated: (app, enabled) => {
    workspaceApps = workspaceApps.map(item => item.workspace_id === app.workspace_id && item.app_id === app.app_id
      ? { ...item, status: enabled ? 'enabled' : 'disabled' } : item);
    appLinksController.invalidate();
    void resources.ensure('apps', true);
  }
});
const agenticBindingController = createAgenticBindingController({
  getSettings: () => platformSettings, render, state: settingsPanelState,
  setSettings: (settings, message) => { platformSettings = { ...platformSettings, ...settings, runtime: platformSettings?.runtime || settings.runtime, computer_use: platformSettings?.computer_use }; notice = { tone: 'success', message }; }
});
const cacheDiagnosticsController = createCacheDiagnosticsController({
  render,
  setNotice: (nextNotice) => {
    notice = nextNotice;
  },
});

const learningController = createLearningController({ render, workspaceId: () => platformSettings?.workspace.workspace_id || '' });

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
  const setting = scalarParam(params.setting);
  focusSetting = ['default-model', 'voice', 'password', 'cache', 'computer-use'].includes(setting) ? setting : '';
  if (pageId) selectedPageId = pageId;
  if (userId && userId !== selectedUserId) {
    selectedUserId = userId;
  }
  resources.cancelExcept(resourcesForPage(selectedPageId));
  render();
  void ensurePageLoaded();
}

function publishSelectedPage(page: SettingsPage) {
  if (page.id === lastPublishedPageId || window.parent === window) {
    return;
  }
  lastPublishedPageId = page.id;
  window.parent.postMessage(
    {
      type: 'loopino.app.selection-changed',
      owner_app_id: 'settings',
      selection: { page_id: page.id }
    },
    "*"
  );
}

function publishSelectedUser(user: User | undefined) {
  if (!user || user.user_id === lastPublishedUserId || window.parent === window) {
    return;
  }
  lastPublishedUserId = user.user_id;
  window.parent.postMessage(
    {
      type: 'loopino.app.selection-changed',
      owner_app_id: 'settings',
      selection: { user_id: user.user_id }
    },
    "*"
  );
}

function publishUserDataChanged() {
  if (window.parent === window) {
    return;
  }
  window.parent.postMessage(
    {
      type: 'loopino.app.data-changed',
      owner_app_id: 'settings',
      resource: 'users'
    },
    "*"
  );
}

const resources = createSettingsResources({
  publish: (resource, raw) => {
    if (resource === 'registry') {
      const registry = raw as { workspace_id: string; items: import('./adminApi').AppRegistryItem[] };
      iconRegistry = registry.items; iconWorkspaceId = registry.workspace_id || platformSettings?.workspace.workspace_id || '';
    }
    else if (resource === 'users') {
      users = (raw as { items: User[] }).items;
      if (!selectedUserId || !users.some(user => user.user_id === selectedUserId)) selectedUserId = users[0]?.user_id || '';
    } else if (resource === 'workspaces') workspaces = (raw as { items: Workspace[] }).items;
    else if (resource === 'apps') workspaceApps = (raw as { items: WorkspaceApp[] }).items;
    else if (resource === 'persistence') persistence = raw as PersistenceStatus;
    else if (resource === 'sessions') {
      if (platformSettings) platformSettings = mergeRuntimeSessionInventory(platformSettings, raw as import('./adminApi').RuntimeSessionInventoryPayload);
      else sessionInventory = raw as import('./adminApi').RuntimeSessionInventoryPayload;
    } else {
      const next = raw as PlatformSettings;
      const previousWorkspaceId = settingsWorkspaceId;
      if (previousWorkspaceId && previousWorkspaceId !== next.workspace.workspace_id) {
        usageVisualizations?.unmountUsageVisualizations();
        resources.reset(); clearSettingsDomCache(); platformSettings = null; users = []; workspaces = []; workspaceApps = []; persistence = null;
        sessionInventory = null; iconRegistry = []; iconWorkspaceId = ''; settingsPanelState.savedDrafts = null;
        appLinksController.reset(); learningController.reset(); providerUsageController.reset(); speechSynthesisController.reset();
        agenticBindingController.reset(); workspaceAppController.reset();
        notice = null;
        Object.assign(sessionsView, createSessionsView());
        queueMicrotask(() => { render(); void ensurePageLoaded(); });
      }
      if (iconRegistry.length && !iconWorkspaceId) iconWorkspaceId = next.workspace.workspace_id;
      settingsWorkspaceId = next.workspace.workspace_id;
      const providersLoaded = resource === 'models' || resource === 'voice';
      platformSettings = mergeSettingsSnapshot(platformSettings, next, resource);
      if (sessionInventory) platformSettings = mergeRuntimeSessionInventory(platformSettings, sessionInventory);
      if (providersLoaded || resource === 'computer-use') syncSettingsPanelDraft(settingsPanelState, platformSettings);
    }
  },
  changed: () => render(),
});
let sessionInventory: import('./adminApi').RuntimeSessionInventoryPayload | null = null;

async function ensurePageLoaded(force = false) {
  const pageId = selectedPageId;
  if (pageId === 'workspace-apps') void resources.ensure('registry', force);
  await Promise.all(resourcesForPage(pageId).map(resource => resources.ensure(resource, force)));
  if (selectedPageId !== pageId) return;
  if (pageId === 'app-links' && resources.state('apps').loaded && resources.state('context').loaded) await ensureAppLinksLoaded(force);
  if (pageId === 'usage' && platformSettings) {
    void providerUsageController.ensureLoaded(force);
    usageVisualizationsRequest ||= import('./components/usageVisualizations').then(module => { usageVisualizations = module; if (selectedPageId === 'usage') render(); }).catch(error => { usageVisualizationsRequest = null; if (selectedPageId === 'usage') showError(error); });
  }
  if (pageId === 'voice' && platformSettings) void speechSynthesisController.load(platformSettings.workspace.workspace_id, force);
  if (pageId === 'learning' && platformSettings) { void learningController.load(force); void resources.ensure('models'); }
  if (pageId === 'cache') void cacheDiagnosticsController.ensureLoaded(force);
}

async function refresh() { await ensurePageLoaded(true); }
async function ensureAppLinksLoaded(force = false) {
  await appLinksController.ensureLoaded(platformSettings?.workspace.workspace_id || '', workspaceApps, force);
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
  users = [...users, created];
  selectedUserId = created.user_id;
  form.reset(); clearSettingsDrafts(form);
  notice = { tone: 'success', message: 'User created.' }; render();
  publishUserDataChanged();
}

async function updateSelectedUser(form: HTMLFormElement, user: User) {
  const data = new FormData(form);
  const updated = await updateAdminUser(user.user_id, {
    display_name: String(data.get('display_name') || ''),
    email: String(data.get('email') || ''),
    platform_role: String(data.get('platform_role') || 'member'),
    account_type: String(data.get('account_type') || 'standard'),
    is_active: data.get('is_active') === 'on'
  });
  users = users.map(item => item.user_id === updated.user_id ? updated : item);
  clearSettingsDrafts(form);
  notice = { tone: 'success', message: 'User updated.' }; render();
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
  form.reset(); clearSettingsDrafts(form);
  notice = { tone: 'success', message: 'Password updated.' };
  render();
}

async function deleteSelectedUser(user: User) {
  const label = user.display_name || user.username;
  if (!await confirmSettingsAction({ title: `Delete ${label}?`,
    detail: 'This permanently removes the user account and its workspace memberships. This action cannot be undone.',
    confirmLabel: 'Delete user' })) return;
  await deleteAdminUser(user.user_id);
  selectedUserId = '';
  notice = { tone: 'success', message: `${label} deleted.` };
  users = users.filter(item => item.user_id !== user.user_id);
  selectedUserId = users[0]?.user_id || ''; render();
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
  const updated = await updateAdminUserMemberships(user.user_id, memberships);
  users = users.map(item => item.user_id === updated.user_id ? updated : item);
  clearSettingsDrafts('.settings-memberships');
  notice = { tone: 'success', message: 'Workspace access updated.' }; render();
  publishUserDataChanged();
}

async function installWorkspaceApp(app: WorkspaceApp) {
  await installWorkspaceAppBinding(app);
  appLinksController.invalidate();
  await resources.ensure('apps', true);
}

async function setWorkspaceAppStatus(app: WorkspaceApp, enabled: boolean) {
  await workspaceAppController.setEnabled(app, enabled);
}

async function uninstallWorkspaceApp(app: WorkspaceApp) {
  await uninstallWorkspaceAppBinding(app);
  appLinksController.invalidate();
  await resources.ensure('apps', true);
}

async function saveDependencySelection(consumerAppId: string, alias: string, providerAppIds: string[]) {
  await appLinksController.saveDependencySelection(consumerAppId, alias, providerAppIds);
}

async function clearRuntimeSessionsFromPanel(sessionIds?: string[]) {
  if (!platformSettings) return;
  const workspaceId = platformSettings.workspace.workspace_id;
  const candidates = scopedSessions(platformSettings, sessionsView);
  const targets = sessionIds?.length ? candidates.filter(session => sessionIds.includes(session.session_id)) : candidates;
  if (!targets.length) return;
  const scope = sessionsView.scope === 'server' ? 'the entire server' : `workspace ${platformSettings.workspace.name}`;
  const active = targets.filter(session => !['closed', 'completed', 'failed', 'terminated', 'stopped'].includes(session.status)).length;
  if (!await confirmSettingsAction({ title: `Delete ${targets.length} runtime session${targets.length === 1 ? '' : 's'}?`,
    detail: `Scope: ${scope}. ${active} sessions may have active agents. Their agents will stop and their conversations, turns and runtime files will be permanently removed.`,
    confirmLabel: 'Delete sessions' })) return;
  if (platformSettings.workspace.workspace_id !== workspaceId) return;
  const scopedIds = targets.map(session => session.session_id);
  settingsPanelState.cleanupError = '';
  settingsPanelState.clearingAllRuntime = !sessionIds?.length;
  scopedIds.forEach(id => settingsPanelState.cleaningSessionIds.add(id));
  render();
  try {
    const payload = await clearRuntimeSessions(scopedIds);
    if (platformSettings.workspace.workspace_id !== workspaceId) return;
    publishRuntimeCleanupChanged(payload);
    platformSettings = mergeRuntimeSessionInventory(platformSettings, payload);
    notice = { tone: 'success', message: `${payload.cleared_sessions} runtime sessions deleted.` };
  } catch (error) {
    settingsPanelState.cleanupError = error instanceof Error ? error.message : 'Unable to delete runtime sessions.';
  } finally {
    scopedIds.forEach(id => settingsPanelState.cleaningSessionIds.delete(id));
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
      type: 'loopino.app.data-changed',
      owner_app_id: 'chat',
      resource: 'threads'
    },
    "*"
  );
  payload.deleted_thread_ids.forEach((threadId) => {
    window.parent.postMessage(
      {
        type: 'loopino.app.data-changed',
        owner_app_id: 'chat',
        resource: 'threads',
        deleted_thread_id: threadId
      },
      "*"
    );
  });
}

function publishAppDependenciesChanged(consumerAppId: string, dependencies: AppDependenciesPayload) {
  if (window.parent === window) {
    return;
  }
  window.parent.postMessage(
    {
      type: 'loopino.app.dependencies-changed',
      app_id: consumerAppId,
      status: dependencies.status
    },
    "*"
  );
}

async function logoutFromSettings() {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'loopino.shell.logout' }, "*");
    return;
  }
  await logout();
  window.location.href = '/';
}

function platformSettingsPageHtml() {
  return settingsPanelHtml(platformSettings, settingsPanelState, selectedPageId);
}

function render() {
  const root = document.getElementById('app');
  if (!root) return;
  if (!draftsRemembered) { rememberSettingsDrafts(root); draftsRemembered = true; }
  const started = performance.now();
  const page = settingsPageById(selectedPageId);
  const dependencies = resourcesForPage(selectedPageId);
  isLoading = dependencies.some(resource => !resources.state(resource).loaded && !resources.state(resource).error);
  const errors = dependencies.filter(resource => resources.state(resource).error && !resources.state(resource).loaded);
  const staleErrors = dependencies.filter(resource => resources.state(resource).error && resources.state(resource).loaded);
  const user = selectedUser();
  if (renderedPageId === 'usage' && (selectedPageId !== 'usage' || isLoading || errors.length)) usageVisualizations?.unmountUsageVisualizations();
  const changedPage = renderedPageId !== selectedPageId;
  renderedPageId = selectedPageId;
  const content = isLoading ? settingsAppSkeletonHtml(page) : errors.length ? errors.map(resource =>
    `<section class="settings-card"><h2>Unable to load ${escapeHtml(resource)}</h2><p role="alert">${escapeHtml(resources.state(resource).error)}</p><button type="button" data-retry-resource="${resource}">Retry</button></section>`).join('') : activeSettingsPageHtml({
      appLinksController, cacheDiagnosticsController, page, persistenceController,
      platformSettingsHtml: platformSettingsPageHtml,
      sessionsHtml: () => platformSettings ? sessionsPageHtml(platformSettings, settingsPanelState, sessionsView) : '',
      usageHtml: () => usagePageHtml(settingsPanelState),
      learningHtml: () => learningPageHtml(learningController.viewState(), platformSettings?.provider.available_providers?.find(p => p.provider_id === 'codex')?.model_options || []),
      selectedUser: user, users, workspaceApps: workspaceAppController.apps(workspaceApps).map(app => ({ ...app, logo: app.workspace_id === iconWorkspaceId ? iconRegistry.find(item => item.app_id === app.app_id)?.logo || null : null })), savingAppKeys: workspaceAppController.savingKeys(), workspaces,
    });
  patchSettingsDom(root, `<main class="settings-shell"><section class="settings-main"><div class="settings-content" data-render-key="${escapeHtml(settingsPageDomKey(settingsWorkspaceId, page.id, user?.user_id))}">
    <header class="detail-header"><div class="detail-title-block"><h2>${escapeHtml(page.title)}</h2><span class="detail-title-separator" aria-hidden="true"></span><p>${escapeHtml(page.summary)}</p></div>
    ${platformSettings ? `<div class="settings-context"><span>${escapeHtml(platformSettings.workspace.name)}</span><span>${escapeHtml(platformSettings.user.display_name || platformSettings.user.username)}</span><button type="button" id="settings-logout" class="settings-secondary">Logout</button></div>` : ''}</header>
    ${noticeHtml(notice)}${staleErrors.map(resource => `<p role="alert">${escapeHtml(resources.state(resource).error)} <button type="button" data-retry-resource="${resource}">Retry</button></p>`).join('')}${content}
    </div></section>${persistenceMigrationModalHtml(persistenceController.viewState())}</main>`);
  bindEvents();
  installationPage.attach(selectedPageId === 'installation' && settingsHostVisible() ? document.getElementById('installation-root') : null);
  syncSettingsModalFocus(persistenceController.cancel);
  learningController.setVisible(selectedPageId === 'learning' && settingsHostVisible() && !isLoading);
  if (selectedPageId === 'usage' && !isLoading && !errors.length) usageVisualizations?.mountUsageVisualizations({ history: settingsPanelState.usageHistory, filters: settingsPanelState.usageHistoryFilters, isLoading: settingsPanelState.isLoadingUsageHistory, onFiltersChange: providerUsageController.updateUsageHistoryFilters, settings: platformSettings });
  if (changedPage) document.querySelector('.settings-main')?.scrollTo?.(0, 0);
  publishSelectedPage(page);
  if (!isLoading && ['users', 'workspace-access'].includes(selectedPageId)) publishSelectedUser(user);
  if (focusSetting && !isLoading) {
    const selectors: Record<string, string> = { 'default-model': '[data-agentic-model-toggle]', voice: '#settings-tts-engine', password: '#reset-password input', cache: '#clear-pwa-cache', 'computer-use': '#settings-computer-use-mode' };
    const target = document.querySelector<HTMLElement>(selectors[focusSetting]);
    if (target) { target.closest('details')?.setAttribute('open', ''); target.focus(); target.scrollIntoView?.({ block: 'center' }); focusSetting = ''; }
  }
  performance.clearMeasures('settings.render');
  performance.measure('settings.render', { start: started, end: performance.now() });
}

function bindEvents() {
  beginSettingsBindings();
  document.querySelectorAll<HTMLElement>('[data-user-discard]').forEach(button => bindControl(button, 'click', () => { const region = button.closest<HTMLElement>('form, #workspace-assignments'); if (region) { if (region instanceof HTMLFormElement) region.reset(); clearSettingsDrafts(region); render(); } }));
  document.querySelectorAll<HTMLElement>('[data-speech-discard]').forEach(button => bindControl(button, 'click', () => { syncSettingsPanelDraft(settingsPanelState, platformSettings, { speech: true }); clearSettingsDrafts('.settings-speech-model-accordion'); render(); }));
  document.querySelectorAll<HTMLElement>('[data-hosted-discard]').forEach(button => bindControl(button, 'click', () => { syncSettingsPanelDraft(settingsPanelState, platformSettings, { hostedModelId: button.dataset.hostedDiscard }); clearSettingsDrafts('[data-hosted-model-accordion]'); render(); }));
  bindControl(document.getElementById('settings-refresh-app-links'), 'click', () => { void ensureAppLinksLoaded(true); });
  document.querySelectorAll<HTMLElement>('[data-retry-resource]').forEach(button => bindControl(button, 'click', () => { void resources.ensure(button.dataset.retryResource as import('./settingsResources').SettingsResource, true).then(() => ensurePageLoaded()); }));
  bindControl(document.getElementById('settings-session-search'), 'input', event => { sessionsView.query = (event.target as HTMLInputElement).value; sessionsView.page = 0; render(); });
  bindControl(document.getElementById('settings-session-status'), 'change', event => { sessionsView.status = (event.target as HTMLSelectElement).value; sessionsView.page = 0; render(); });
  bindControl(document.getElementById('settings-session-scope'), 'change', event => { sessionsView.scope = (event.target as HTMLSelectElement).value === 'server' ? 'server' : 'workspace'; sessionsView.page = 0; sessionsView.status = ''; clearSettingsDrafts('.settings-session-filters'); render(); });
  bindControl(document.getElementById('settings-sessions-prev'), 'click', () => { sessionsView.page -= 1; render(); });
  bindControl(document.getElementById('settings-sessions-next'), 'click', () => { sessionsView.page += 1; render(); });
  bindControl(document.getElementById('create-workspace'), 'submit', event => { event.preventDefault(); const form = event.target as HTMLFormElement; void requestJson('/api/workspaces', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form))) }).then(async () => { form.reset(); clearSettingsDrafts('#create-workspace'); await resources.ensure('workspaces', true); await resources.ensure('apps', true); notice = { tone: 'success', message: 'Workspace created.' }; render(); }).catch(showError); });
  speechSynthesisController.bind();
  learningController.bind();
  computerUseController.bind();
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
    activateNativeProviderFromPanel: agenticBindingController.activateProvider,
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
    saveSpeechProviderSettingsFromPanel: () => saveSpeechProviderSettings(providerSettingsActionContext()),
    selectedUser,
    selectUser: (userId) => {
      selectedUserId = userId;
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
    getSettings: () => platformSettings,
    state: settingsPanelState
  };
}

function showError(error: unknown) {
  const message = error instanceof Error ? error.message : 'Unexpected error';
  notice = { tone: 'error', message };
  render();
}

bindSettingsHostEvents({
  navigate: applyNavigationParams,
  visibilityChanged: (visible) => {
    learningController.setVisible(selectedPageId === 'learning' && visible && !isLoading);
    installationPage.attach(visible && selectedPageId === 'installation' ? document.getElementById('installation-root') : null);
  },
});

refresh().catch(showError);
