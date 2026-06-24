import type { AppDependenciesPayload, AppRegistryItem, DependencyResolutionItem, WorkspaceApp } from './adminApi';
import { escapeAttr, escapeHtml } from './html';

export function appLinksPageHtml({
  appRegistry,
  dependencies,
  error,
  isLoading,
  loadErrors,
  savingKeys,
  workspaceApps,
}: {
  appRegistry: AppRegistryItem[];
  dependencies: AppDependenciesPayload[];
  error: string;
  isLoading: boolean;
  loadErrors: Array<{ app_id: string; message: string; name: string }>;
  savingKeys: Set<string>;
  workspaceApps: WorkspaceApp[];
}) {
  return `<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${error ? `<p class="settings-platform-error">${escapeHtml(error)}</p>` : ''}
      ${loadErrors.length ? `<div class="settings-app-link-errors">${loadErrors.map(loadErrorHtml).join('')}</div>` : ''}
      ${dependencies.length > 1 ? consumerNavHtml(dependencies, appRegistry, workspaceApps) : ''}
      <div class="settings-app-link-list">
        ${dependencies.length ? dependencies.map((payload) => consumerDependencyHtml(payload, appRegistry, workspaceApps, savingKeys)).join('') : emptyStateHtml(error, isLoading)}
      </div>
    </section>`;
}

function consumerNavHtml(
  dependencies: AppDependenciesPayload[],
  appRegistry: AppRegistryItem[],
  workspaceApps: WorkspaceApp[]
) {
  return `<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${dependencies.map((payload) => {
      const app = workspaceApps.find((item) => item.workspace_id === payload.workspace_id && item.app_id === payload.consumer_app_id);
      const registryApp = appById(appRegistry, payload.consumer_app_id);
      const label = app?.name || registryApp?.name || payload.consumer_app_id;
      return `<a class="settings-app-link-consumer-nav__item" href="#${escapeAttr(consumerAnchorId(payload.consumer_app_id))}">
        <strong>${escapeHtml(label)}</strong>
        <small>${escapeHtml(String(payload.dependencies.length))}</small>
      </a>`;
    }).join('')}
  </nav>`;
}

function consumerDependencyHtml(
  payload: AppDependenciesPayload,
  appRegistry: AppRegistryItem[],
  workspaceApps: WorkspaceApp[],
  savingKeys: Set<string>
) {
  const app = workspaceApps.find((item) => item.workspace_id === payload.workspace_id && item.app_id === payload.consumer_app_id);
  const registryApp = appById(appRegistry, payload.consumer_app_id);
  return `<article class="settings-app-link-consumer" id="${escapeAttr(consumerAnchorId(payload.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${appIconHtml(registryApp, payload.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${escapeHtml(app?.name || payload.consumer_app_id)}</strong>
        <small>${escapeHtml(payload.consumer_app_id)} - ${escapeHtml(payload.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${payload.dependencies.map((dependency) => dependencyHtml(payload.consumer_app_id, dependency, appRegistry, savingKeys)).join('')}
    </div>
  </article>`;
}

function dependencyHtml(
  consumerAppId: string,
  dependency: DependencyResolutionItem,
  appRegistry: AppRegistryItem[],
  savingKeys: Set<string>
) {
  const isSaving = savingKeys.has(dependencyKey(consumerAppId, dependency.alias));
  const effectiveSelectedIds = effectiveProviderIds(dependency);
  const automaticProviderId = automaticProviderIdFor(dependency);
  return `<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${escapeHtml(dependency.alias)}</strong>
        <small>${escapeHtml(dependency.interface)} ${escapeHtml(dependency.version)}</small>
      </span>
      <span class="settings-pill ${dependency.status === 'resolved' || automaticProviderId ? '' : 'settings-pill-muted'}">${escapeHtml(statusLabel(dependency, automaticProviderId))}</span>
    </header>
    <p class="settings-card-copy">${escapeHtml(dependency.description || 'No description.')}</p>
    ${dependency.blocked_reason ? `<p class="settings-platform-error">${escapeHtml(dependency.blocked_reason)}</p>` : ''}
    ${dependency.stale_provider_app_ids.length ? `<p class="settings-platform-error">Unavailable selection: ${escapeHtml(dependency.stale_provider_app_ids.join(', '))}</p>` : ''}
    ${
      dependency.candidates.length
        ? `<div class="settings-app-link-candidates">
            ${dependency.candidates.map((candidate) => {
              const checked = effectiveSelectedIds.includes(candidate.app_id);
              const choiceType = dependency.cardinality === 'many' ? 'checkbox' : 'radio';
              const inputName = `dependency:${consumerAppId}:${dependency.alias}`;
              const candidateApp = appById(appRegistry, candidate.app_id);
              return `<label class="settings-app-link-candidate ${checked ? 'is-selected' : ''}">
                <input
                  ${checked ? 'checked' : ''}
                  ${isSaving ? 'disabled' : ''}
                  data-dependency-choice="${escapeAttr(choiceKey(consumerAppId, dependency.alias, candidate.app_id))}"
                  name="${escapeAttr(inputName)}"
                  type="${choiceType}"
                />
                ${appIconHtml(candidateApp, candidate.app_id)}
                <span>
                  <strong>${escapeHtml(candidate.name || candidate.app_id)}</strong>
                  <small>${escapeHtml(candidate.app_id)} - ${escapeHtml(candidate.interface_version)}${candidate.app_id === automaticProviderId ? ' - automatic default' : ''}</small>
                </span>
              </label>`;
            }).join('')}
          </div>`
        : '<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'
    }
    ${
      automaticProviderId
        ? `<button type="button" class="settings-secondary" data-dependency-save-default="${escapeAttr(choiceKey(consumerAppId, dependency.alias, automaticProviderId))}" ${isSaving ? 'disabled' : ''}>
          <span class="material-symbols-rounded" aria-hidden="true">${isSaving ? 'sync' : 'save'}</span>
          ${isSaving ? 'Saving' : 'Save default'}
        </button>`
        : ''
    }
  </section>`;
}

function emptyStateHtml(error: string, isLoading: boolean) {
  if (error) {
    return '';
  }
  if (isLoading) {
    return '<p class="settings-card-copy">Loading app links...</p>';
  }
  return '<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>';
}

function dependencyKey(consumerAppId: string, alias: string) {
  return `${consumerAppId}:${alias}`;
}

function choiceKey(consumerAppId: string, alias: string, providerAppId: string) {
  return `${consumerAppId}:${alias}:${providerAppId}`;
}

function consumerAnchorId(consumerAppId: string) {
  return `settings-app-link-consumer-${consumerAppId}`;
}

function effectiveProviderIds(dependency: DependencyResolutionItem) {
  if (dependency.selected_provider_app_ids.length) {
    return dependency.selected_provider_app_ids;
  }
  const automaticProviderId = automaticProviderIdFor(dependency);
  return automaticProviderId ? [automaticProviderId] : [];
}

function automaticProviderIdFor(dependency: DependencyResolutionItem) {
  if (
    dependency.selected_provider_app_ids.length ||
    dependency.status !== 'optional_unset' ||
    dependency.cardinality !== 'one' ||
    dependency.stale_provider_app_ids.length ||
    dependency.blocked_reason
  ) {
    return '';
  }
  return dependency.candidates[0]?.app_id || '';
}

function statusLabel(dependency: DependencyResolutionItem, automaticProviderId: string) {
  if (automaticProviderId) {
    return 'auto default';
  }
  if (dependency.status === 'optional_unset') {
    return 'unset';
  }
  return dependency.status;
}

function appById(appRegistry: AppRegistryItem[], appId: string): AppRegistryItem | null {
  return appRegistry.find((item) => item.app_id === appId) || null;
}

function loadErrorHtml(error: { app_id: string; message: string; name: string }) {
  return `<p class="settings-platform-error">${escapeHtml(error.name || error.app_id)}: ${escapeHtml(error.message)}</p>`;
}

function appIconHtml(app: AppRegistryItem | null, fallbackAppId: string) {
  if (app?.logo?.kind === 'image' && app.logo.value) {
    return `<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${escapeAttr(app.logo.value)}" /></span>`;
  }
  const icon = app?.logo?.value || defaultIcon(app, fallbackAppId);
  return `<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${escapeHtml(icon)}</span></span>`;
}

function defaultIcon(app: AppRegistryItem | null, fallbackAppId: string): string {
  const iconByAppId: Record<string, string> = {
    agents: 'smart_toy',
    'app-store': 'storefront',
    'base-shell': 'dashboard',
    chat: 'forum',
    checklist: 'checklist',
    crm: 'contacts',
    'developer-kit': 'developer_board',
    'docs-studio': 'description',
    'document-generator': 'description',
    'dynamic-views': 'dashboard_customize',
    'gmail-app': 'mail',
    memory: 'database',
    'maverick-monitor': 'monitor_heart',
    settings: 'admin_panel_settings',
    skills: 'school',
    speech: 'record_voice_over',
    storage: 'cloud',
    'website-studio': 'web_asset'
  };
  if (iconByAppId[fallbackAppId]) {
    return iconByAppId[fallbackAppId];
  }
  if (app?.views.includes('chat')) {
    return 'forum';
  }
  if (app?.views.includes('agents')) {
    return 'smart_toy';
  }
  if (app?.views.includes('shell')) {
    return 'dashboard';
  }
  return 'apps';
}
