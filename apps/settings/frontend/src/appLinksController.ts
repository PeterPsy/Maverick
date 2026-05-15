import {
  getAppDependencies,
  loadAppRegistry,
  saveAppDependencySelection,
  type AppDependenciesPayload,
  type AppRegistryItem,
  type WorkspaceApp
} from './adminApi';

type DependencyLoadResult =
  | { app: WorkspaceApp; payload: AppDependenciesPayload }
  | { app: WorkspaceApp; error: string };

export type AppLinkLoadError = {
  app_id: string;
  message: string;
  name: string;
};

export type AppLinksViewState = {
  appRegistry: AppRegistryItem[];
  dependencies: AppDependenciesPayload[];
  error: string;
  isLoading: boolean;
  loadErrors: AppLinkLoadError[];
  savingKeys: Set<string>;
};

export function createAppLinksController({
  publishChanged,
  render,
  setNotice
}: {
  publishChanged: (consumerAppId: string, dependencies: AppDependenciesPayload) => void;
  render: () => void;
  setNotice: (notice: { tone: 'success'; message: string }) => void;
}) {
  let appRegistry: AppRegistryItem[] = [];
  let dependencies: AppDependenciesPayload[] = [];
  let error = '';
  let loadErrors: AppLinkLoadError[] = [];
  let loadedWorkspaceId = '';
  let isLoading = false;
  let savingKeys = new Set<string>();

  function viewState(): AppLinksViewState {
    return { appRegistry, dependencies, error, isLoading, loadErrors, savingKeys };
  }

  function reset() {
    appRegistry = [];
    dependencies = [];
    error = '';
    loadErrors = [];
    loadedWorkspaceId = '';
  }

  function invalidate() {
    loadedWorkspaceId = '';
  }

  async function ensureLoaded(workspaceId: string, workspaceApps: WorkspaceApp[], force = false) {
    if (!workspaceId || isLoading) {
      return;
    }
    if (!force && loadedWorkspaceId === workspaceId) {
      return;
    }
    isLoading = true;
    error = '';
    loadErrors = [];
    render();
    try {
      const [registryPayload, dependenciesPayload] = await Promise.all([
        loadAppRegistry(),
        loadDependenciesForWorkspace(workspaceId, workspaceApps)
      ]);
      appRegistry = registryPayload;
      dependencies = dependenciesPayload;
      loadedWorkspaceId = workspaceId;
    } catch (loadError) {
      dependencies = [];
      loadedWorkspaceId = '';
      error = loadError instanceof Error ? loadError.message : 'Unable to load app links.';
    } finally {
      isLoading = false;
      render();
    }
  }

  async function saveDependencySelection(consumerAppId: string, alias: string, providerAppIds: string[]) {
    const key = dependencyKey(consumerAppId, alias);
    savingKeys = new Set([...savingKeys, key]);
    render();
    try {
      const payload = await saveAppDependencySelection(consumerAppId, alias, providerAppIds);
      dependencies = dependencies.map((item) => (item.consumer_app_id === consumerAppId ? payload : item));
      publishChanged(consumerAppId, payload);
      setNotice({ tone: 'success', message: 'App link updated.' });
    } finally {
      const nextSavingKeys = new Set(savingKeys);
      nextSavingKeys.delete(key);
      savingKeys = nextSavingKeys;
      render();
    }
  }

  async function loadDependenciesForWorkspace(workspaceId: string, apps: WorkspaceApp[]) {
    const enabledApps = apps.filter((app) => app.workspace_id === workspaceId && app.status === 'enabled');
    const results: DependencyLoadResult[] = await Promise.all(
      enabledApps.map(async (app) => {
        try {
          return { app, payload: await getAppDependencies(app.app_id) };
        } catch (appError) {
          return { app, error: appError instanceof Error ? appError.message : 'Unable to load app links.' };
        }
      })
    );
    loadErrors = results
      .filter((result): result is { app: WorkspaceApp; error: string } => 'error' in result)
      .map((result) => ({ app_id: result.app.app_id, message: result.error, name: result.app.name || result.app.app_id }));
    return results
      .filter((result): result is { app: WorkspaceApp; payload: AppDependenciesPayload } => 'payload' in result && result.payload.dependencies.length > 0)
      .map((result) => result.payload)
      .sort((left, right) => left.consumer_app_id.localeCompare(right.consumer_app_id));
  }

  return {
    ensureLoaded,
    invalidate,
    reset,
    saveDependencySelection,
    viewState
  };
}

function dependencyKey(consumerAppId: string, alias: string) {
  return `${consumerAppId}:${alias}`;
}
