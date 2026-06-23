import type { AppDependenciesPayload, User, WorkspaceApp } from './adminApi';
import type { createPersistenceController, MigrationTargetDraft } from './persistenceController';
import { bindSettingsPanelEvents } from './settingsPanel';

type PersistenceController = ReturnType<typeof createPersistenceController>;

export function bindSettingsEvents(context: {
  clearRuntimeSessionsFromPanel: (sessionIds?: string[]) => Promise<void>;
  createUser: (form: HTMLFormElement) => Promise<void>;
  deleteSelectedUser: (user: User) => Promise<void>;
  dismissNotice: () => void;
  installWorkspaceApp: (app: WorkspaceApp) => Promise<void>;
  logoutFromSettings: () => Promise<void>;
  onHostedProviderModelChanged: (modelId: string) => void;
  onProviderModelChanged: (modelId: string) => void;
  onProviderReasoningChanged: (reasoningEffort: string) => void;
  persistenceController: PersistenceController;
  render: () => void;
  resetSelectedUserPassword: (form: HTMLFormElement, user: User) => Promise<void>;
  saveDependencySelection: (consumerAppId: string, alias: string, providerAppIds: string[]) => Promise<void>;
  saveHostedProviderSettingsFromPanel: () => Promise<void>;
  saveProviderSettingsFromPanel: () => Promise<void>;
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
  document.getElementById('dismiss-notice')?.addEventListener('click', context.dismissNotice);
  document.getElementById('create-user')?.addEventListener('submit', (event) => {
    event.preventDefault();
    context.createUser(event.currentTarget as HTMLFormElement).catch(context.showError);
  });
  const user = context.selectedUser();
  document.getElementById('selected-user')?.addEventListener('change', (event) => {
    context.selectUser((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('edit-user')?.addEventListener('submit', (event) => {
    event.preventDefault();
    if (user) context.updateSelectedUser(event.currentTarget as HTMLFormElement, user).catch(context.showError);
  });
  document.getElementById('reset-password')?.addEventListener('submit', (event) => {
    event.preventDefault();
    if (user) context.resetSelectedUserPassword(event.currentTarget as HTMLFormElement, user).catch(context.showError);
  });
  document.getElementById('delete-user')?.addEventListener('click', () => {
    if (user) context.deleteSelectedUser(user).catch(context.showError);
  });
  document.getElementById('save-memberships')?.addEventListener('click', () => {
    if (user) context.updateMemberships(user).catch(context.showError);
  });
  bindWorkspaceAppEvents(context);
  bindAppLinkEvents(context);
  bindPersistenceEvents(context);
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
    onHostedProviderModelChanged: context.onHostedProviderModelChanged,
    onProviderModelChanged: context.onProviderModelChanged,
    onProviderReasoningChanged: context.onProviderReasoningChanged,
    onSaveHostedProviderSettings: () => {
      context.saveHostedProviderSettingsFromPanel().catch(context.showError);
    },
    onSaveProviderSettings: () => {
      context.saveProviderSettingsFromPanel().catch(context.showError);
    },
  });
}

function bindAppLinkEvents(context: {
  appDependencies: () => AppDependenciesPayload[];
  saveDependencySelection: (consumerAppId: string, alias: string, providerAppIds: string[]) => Promise<void>;
  showError: (error: unknown) => void;
}) {
  document.querySelectorAll<HTMLInputElement>('[data-dependency-choice]').forEach((input) => {
    input.addEventListener('change', () => {
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
    button.addEventListener('click', () => {
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
    input.addEventListener('change', () => {
      const app = context.workspaceApps().find((item) => `${item.workspace_id}:${item.app_id}` === input.dataset.appToggle);
      if (app) context.setWorkspaceAppStatus(app, input.checked).catch(context.showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-app-install]').forEach((button) => {
    button.addEventListener('click', () => {
      const app = context.workspaceApps().find((item) => `${item.workspace_id}:${item.app_id}` === button.dataset.appInstall);
      if (app) context.installWorkspaceApp(app).catch(context.showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-app-uninstall]').forEach((button) => {
    button.addEventListener('click', () => {
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
    button.addEventListener('click', () => {
      const target = button.dataset.adapterTarget;
      if (target === 'json' || target === 'mongo') {
        context.persistenceController.prepare(target).catch(context.showError);
      }
    });
  });
  document.getElementById('close-migration-modal')?.addEventListener('click', () => {
    context.persistenceController.cancel();
  });
  document.getElementById('cancel-migration')?.addEventListener('click', () => {
    context.persistenceController.cancel();
  });
  document.getElementById('validate-migration')?.addEventListener('click', () => {
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
    input.addEventListener('input', () => updateMigrationDraft(false));
    input.addEventListener('change', () => updateMigrationDraft(true));
  });
  document.getElementById('settings-delete-source')?.addEventListener('change', (event) => {
    context.persistenceController.setDeleteSource((event.currentTarget as HTMLInputElement).checked);
  });
  document.getElementById('confirm-migration')?.addEventListener('click', () => {
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
