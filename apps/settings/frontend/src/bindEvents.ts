import { runSettingsAction } from './settingsActions';
import { bindControl } from './controlBindings';
import type { AppDependenciesPayload, User, WorkspaceApp } from './adminApi';
import type { createPersistenceController, MigrationTargetDraft } from './persistenceController';
import { bindSettingsPanelEvents } from './settingsPanelEvents';
import { bindBouncyToggles } from './bouncyToggle';
import type { createCacheDiagnosticsController } from './cacheDiagnosticsController';

type PersistenceController = ReturnType<typeof createPersistenceController>;
type CacheDiagnosticsController = ReturnType<typeof createCacheDiagnosticsController>;

export function bindSettingsEvents(context: {
  cacheDiagnosticsController: CacheDiagnosticsController;
  clearRuntimeSessionsFromPanel: (sessionIds?: string[]) => Promise<void>;
  createUser: (form: HTMLFormElement) => Promise<void>;
  deleteSelectedUser: (user: User) => Promise<void>;
  dismissNotice: () => void;
  installWorkspaceApp: (app: WorkspaceApp) => Promise<void>;
  logoutFromSettings: () => Promise<void>;
  onHostedProviderRoutingChanged: (modelId: string, field: string, value: string | boolean) => void;
  activateNativeProviderFromPanel: (providerId: string) => Promise<void>;
  saveAgenticBindingFromPanel: (
    definitionId: string,
    options?: { enabled?: boolean }
  ) => Promise<void>;
  refreshProviderUsageFromPanel: () => Promise<void>;
  onSpeechAudioModelChanged: (modelId: string) => void;
  onSpeechConversationModelChanged: (modelId: string) => void;
  persistenceController: PersistenceController;
  render: () => void;
  resetSelectedUserPassword: (form: HTMLFormElement, user: User) => Promise<void>;
  saveDependencySelection: (consumerAppId: string, alias: string, providerAppIds: string[]) => Promise<void>;
  saveHostedProviderSettingsFromPanel: (modelId?: string) => Promise<void>;
  saveSpeechProviderSettingsFromPanel: () => Promise<void>;
  selectedUser: () => User | undefined;
  selectUser: (userId: string) => void;
  setWorkspaceAppStatus: (app: WorkspaceApp, enabled: boolean) => Promise<void>;
  showError: (error: unknown) => void;
  uninstallWorkspaceApp: (app: WorkspaceApp) => Promise<void>;
  updateMemberships: (user: User) => Promise<void>;
  updateSelectedUser: (form: HTMLFormElement, user: User) => Promise<void>;
  workspaceApps: () => WorkspaceApp[];
  appDependencies: () => AppDependenciesPayload[];
}) {
  bindBouncyToggles();
  bindControl(document.getElementById('dismiss-notice'), 'click', context.dismissNotice);
  bindControl(document.getElementById('create-user'), 'submit', (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    void runSettingsAction(form, () => context.createUser(form), context.showError);
  });
  const user = context.selectedUser();
  bindControl(document.getElementById('selected-user'), 'change', (event) => {
    context.selectUser((event.currentTarget as HTMLSelectElement).value);
  });
  bindControl(document.getElementById('edit-user'), 'submit', (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (user) void runSettingsAction(form, () => context.updateSelectedUser(form, user), context.showError);
  });
  bindControl(document.getElementById('reset-password'), 'submit', (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (user) void runSettingsAction(form, () => context.resetSelectedUserPassword(form, user), context.showError);
  });
  bindControl(document.getElementById('delete-user'), 'click', () => {
    if (user) context.deleteSelectedUser(user).catch(context.showError);
  });
  bindControl(document.getElementById('save-memberships'), 'click', () => {
    if (user) void runSettingsAction(document.getElementById('workspace-assignments'), () => context.updateMemberships(user), context.showError);
  });
  bindWorkspaceAppEvents(context);
  bindAppLinkEvents(context);
  bindPersistenceEvents(context);
  bindCacheDiagnosticsEvents(context);
  bindSettingsPanelEvents({
    onClearAllRuntimeSessions: () => {
      context.clearRuntimeSessionsFromPanel().catch(context.showError);
    },
    onClearRuntimeSession: (sessionId) => {
      if (sessionId) {
        context.clearRuntimeSessionsFromPanel([sessionId]).catch(context.showError);
      }
    },
    onLogout: () => {
      context.logoutFromSettings().catch(context.showError);
    },
    onHostedProviderRoutingChanged: context.onHostedProviderRoutingChanged,
    onActivateNativeProvider: (providerId) => {
      context.activateNativeProviderFromPanel(providerId).catch(context.showError);
    },
    onSaveAgenticBinding: (definitionId, options) => {
      context.saveAgenticBindingFromPanel(definitionId, options).catch(context.showError);
    },
    onRefreshProviderUsage: () => {
      context.refreshProviderUsageFromPanel().catch(context.showError);
    },
    onSpeechAudioModelChanged: context.onSpeechAudioModelChanged,
    onSpeechConversationModelChanged: context.onSpeechConversationModelChanged,
    onSaveHostedProviderSettings: (modelId) => {
      context.saveHostedProviderSettingsFromPanel(modelId).catch(context.showError);
    },
    onSaveSpeechProviderSettings: () => {
      context.saveSpeechProviderSettingsFromPanel().catch(context.showError);
    },
  });
}

export function bindCacheDiagnosticsEvents(context: {
  cacheDiagnosticsController: CacheDiagnosticsController;
  showError: (error: unknown) => void;
}) {
  bindControl(document.getElementById('refresh-pwa-cache'), 'click', () => {
    context.cacheDiagnosticsController.ensureLoaded(true).catch(context.showError);
  });
  bindControl(document.getElementById('clear-pwa-cache'), 'click', () => {
    context.cacheDiagnosticsController.clear().catch(context.showError);
  });

}

function bindAppLinkEvents(context: {
  appDependencies: () => AppDependenciesPayload[];
  saveDependencySelection: (consumerAppId: string, alias: string, providerAppIds: string[]) => Promise<void>;
  showError: (error: unknown) => void;
}) {
  document.querySelectorAll<HTMLInputElement>('[data-dependency-choice]').forEach((input) => {
    bindControl(input, 'change', () => {
      const choice = parseDependencyChoice(input.dataset.dependencyChoice || '');
      if (!choice) {
        return;
      }
      const dependency = context
        .appDependencies()
        .find((payload) => payload.consumer_app_id === choice.consumerAppId)
        ?.dependencies.find((item) => item.alias === choice.alias);
      if (!dependency) {
        return;
      }
      if (dependency.cardinality === 'one') {
        context.saveDependencySelection(choice.consumerAppId, choice.alias, [choice.providerAppId]).catch(context.showError);
        return;
      }
      const selected = new Set(dependency.selected_provider_app_ids);
      if (input.checked) {
        selected.add(choice.providerAppId);
      } else {
        selected.delete(choice.providerAppId);
      }
      context.saveDependencySelection(choice.consumerAppId, choice.alias, Array.from(selected)).catch(context.showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-dependency-save-default]').forEach((button) => {
    bindControl(button, 'click', () => {
      const choice = parseDependencyChoice(button.dataset.dependencySaveDefault || '');
      if (choice) {
        context.saveDependencySelection(choice.consumerAppId, choice.alias, [choice.providerAppId]).catch(context.showError);
      }
    });
  });
}

function parseDependencyChoice(value: string) {
  const [consumerAppId, alias, ...providerParts] = value.split(':');
  const providerAppId = providerParts.join(':');
  if (!consumerAppId || !alias || !providerAppId) {
    return null;
  }
  return { alias, consumerAppId, providerAppId };
}

function bindWorkspaceAppEvents(context: {
  installWorkspaceApp: (app: WorkspaceApp) => Promise<void>;
  setWorkspaceAppStatus: (app: WorkspaceApp, enabled: boolean) => Promise<void>;
  showError: (error: unknown) => void;
  uninstallWorkspaceApp: (app: WorkspaceApp) => Promise<void>;
  workspaceApps: () => WorkspaceApp[];
}) {
  document.querySelectorAll<HTMLInputElement>('[data-app-toggle]').forEach((input) => {
    bindControl(input, 'change', () => {
      const app = context.workspaceApps().find((item) => `${item.workspace_id}:${item.app_id}` === input.dataset.appToggle);
      if (app) context.setWorkspaceAppStatus(app, input.checked).catch(context.showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-app-install]').forEach((button) => {
    bindControl(button, 'click', () => {
      const app = context.workspaceApps().find((item) => `${item.workspace_id}:${item.app_id}` === button.dataset.appInstall);
      if (app) context.installWorkspaceApp(app).catch(context.showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-app-uninstall]').forEach((button) => {
    bindControl(button, 'click', () => {
      const app = context.workspaceApps().find((item) => `${item.workspace_id}:${item.app_id}` === button.dataset.appUninstall);
      if (app) context.uninstallWorkspaceApp(app).catch(context.showError);
    });
  });
}

function bindPersistenceEvents(context: {
  persistenceController: PersistenceController;
  showError: (error: unknown) => void;
}) {
  document.querySelectorAll<HTMLButtonElement>('[data-adapter-target]').forEach((button) => {
    bindControl(button, 'click', () => {
      const target = button.dataset.adapterTarget;
      if (target === 'json' || target === 'mongo') {
        context.persistenceController.prepare(target).catch(context.showError);
      }
    });
  });
  bindControl(document.getElementById('close-migration-modal'), 'click', () => {
    context.persistenceController.cancel();
  });
  bindControl(document.getElementById('cancel-migration'), 'click', () => {
    context.persistenceController.cancel();
  });
  bindControl(document.getElementById('validate-migration'), 'click', () => {
    context.persistenceController.validateDraft().catch(context.showError);
  });
  document.querySelectorAll<HTMLInputElement>('[data-migration-field]').forEach((input) => {
    const updateMigrationDraft = (render: boolean) => {
      const field = input.dataset.migrationField;
      if (field && field in (context.persistenceController.viewState().targetDraft || {})) {
        const hadReviewedPlan = Boolean(context.persistenceController.viewState().migrationPlan);
        context.persistenceController.updateDraft(field as keyof MigrationTargetDraft, input.value, { render });
        if (!render && hadReviewedPlan) {
          markMigrationDraftStale();
        }
      }
    };
    bindControl(input, 'input', () => updateMigrationDraft(false));
    bindControl(input, 'change', () => updateMigrationDraft(true));
  });
  bindControl(document.getElementById('settings-delete-source'), 'change', (event) => {
    context.persistenceController.setDeleteSource((event.currentTarget as HTMLInputElement).checked);
  });
  bindControl(document.getElementById('confirm-migration'), 'click', () => {
    context.persistenceController.apply().catch(context.showError);
  });
}

function markMigrationDraftStale() {
  const confirmButton = document.getElementById('confirm-migration') as HTMLButtonElement | null;
  if (confirmButton) {
    confirmButton.disabled = true;
  }
  const plan = document.querySelector<HTMLElement>('.settings-migration-plan');
  if (!plan) {
    return;
  }
  const icon = plan.querySelector<HTMLElement>('.material-symbols-rounded');
  const title = plan.querySelector<HTMLElement>('strong');
  const detail = plan.querySelector<HTMLElement>('small');
  if (icon) {
    icon.textContent = 'rule';
  }
  if (title) {
    title.textContent = 'Dry run changed';
  }
  if (detail) {
    detail.textContent = 'Validate the dry run again before applying migration.';
  }
  plan.querySelector<HTMLElement>('.settings-migration-collections')?.remove();
}
