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
  let generation = 0;
  let savingKeys = new Set<string>();

  function viewState(): AppLinksViewState {
    return { appRegistry, dependencies, error, isLoading, loadErrors, savingKeys };
  }

  function reset() {
    generation += 1; isLoading = false;
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
    const request = ++generation;
    isLoading = true;
    error = '';
    loadErrors = [];
    render();
    try {
      const [registryPayload, dependenciesPayload] = await Promise.all([
        loadAppRegistry(),
        loadDependenciesForWorkspace(workspaceId, workspaceApps)
      ]);
      if (request !== generation) return;
      appRegistry = registryPayload;
      dependencies = dependenciesPayload.dependencies;
      loadErrors = dependenciesPayload.errors;
      loadedWorkspaceId = workspaceId;
    } catch (loadError) {
      if (request !== generation) return;
      loadedWorkspaceId = '';
      error = loadError instanceof Error ? loadError.message : 'Unable to load app links.';
    } finally {
      if (request !== generation) return;
      isLoading = false;
      render();
    }
  }

  async function saveDependencySelection(consumerAppId: string, alias: string, providerAppIds: string[]) {
    const request = generation;
    const key = dependencyKey(consumerAppId, alias);
    savingKeys = new Set([...savingKeys, key]);
    render();
    try {
      const payload = await saveAppDependencySelection(consumerAppId, alias, providerAppIds);
      if (request !== generation) return;
      dependencies = dependencies.map((item) => (item.consumer_app_id === consumerAppId ? payload : item));
      publishChanged(consumerAppId, payload);
      setNotice({ tone: 'success', message: 'App link updated.' });
    } finally {
      if (request !== generation) return;
      const nextSavingKeys = new Set(savingKeys);
      nextSavingKeys.delete(key);
      savingKeys = nextSavingKeys;
      render();
    }
  }

  async function loadDependenciesForWorkspace(workspaceId: string, apps: WorkspaceApp[]) {
    const enabledApps = apps.filter((app) => app.workspace_id === workspaceId && app.status === 'enabled');
    const results: DependencyLoadResult[] = new Array(enabledApps.length);
    let cursor = 0;
    const request = generation;
    await Promise.all(Array.from({ length: Math.min(4, enabledApps.length) }, async () => {
      while (cursor < enabledApps.length && request === generation) {
        const index = cursor++;
        const app = enabledApps[index];
        try { results[index] = { app, payload: await getAppDependencies(app.app_id) }; }
        catch (appError) { results[index] = { app, error: appError instanceof Error ? appError.message : 'Unable to load app links.' }; }
      }
    }));
    const completed = results.filter(Boolean);
    const errors = completed

      .filter((result): result is { app: WorkspaceApp; error: string } => 'error' in result)
      .map((result) => ({ app_id: result.app.app_id, message: result.error, name: result.app.name || result.app.app_id }));
    const dependencies = completed
      .filter((result): result is { app: WorkspaceApp; payload: AppDependenciesPayload } => 'payload' in result && result.payload.dependencies.length > 0)
      .map((result) => result.payload)
      .sort((left, right) => left.consumer_app_id.localeCompare(right.consumer_app_id));
    return { dependencies, errors };
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
