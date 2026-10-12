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
  let workspaceGeneration = 0;
  let readGeneration = 0;
  let workspaceId = '';
  const pendingSelections = new Map<string, { providerAppIds: string[] }>();

  function viewState(): AppLinksViewState {
    return {
      appRegistry, error, isLoading, loadErrors, savingKeys: new Set(pendingSelections.keys()),
      dependencies: dependencies.map(item => ({ ...item, dependencies: item.dependencies.map(dependency => {
        const pending = pendingSelections.get(dependencyKey(item.consumer_app_id, dependency.alias));
        return pending ? { ...dependency, selected_provider_app_ids: pending.providerAppIds } : dependency;
      }) }))
    };
  }

  function reset() {
    workspaceGeneration += 1; readGeneration += 1; isLoading = false;
    workspaceId = '';
    pendingSelections.clear();
    appRegistry = [];
    dependencies = [];
    error = '';
    loadErrors = [];
    loadedWorkspaceId = '';
  }

  function invalidate() {
    loadedWorkspaceId = '';
  }

  async function ensureLoaded(nextWorkspaceId: string, workspaceApps: WorkspaceApp[], force = false) {
    if (!nextWorkspaceId) return;
    if (workspaceId !== nextWorkspaceId) { reset(); workspaceId = nextWorkspaceId; }
    if (isLoading) {
      return;
    }
    if (!force && loadedWorkspaceId === workspaceId) {
      return;
    }
    const request = ++readGeneration;
    isLoading = true;
    error = '';
    loadErrors = [];
    render();
    try {
      const [registryPayload, dependenciesPayload] = await Promise.all([
        loadAppRegistry(),
        loadDependenciesForWorkspace(workspaceId, workspaceApps)
      ]);
      if (request !== readGeneration) return;
      appRegistry = registryPayload;
      dependencies = dependenciesPayload.dependencies;
      loadErrors = dependenciesPayload.errors;
      loadedWorkspaceId = workspaceId;
    } catch (loadError) {
      if (request !== readGeneration) return;
      loadedWorkspaceId = '';
      error = loadError instanceof Error ? loadError.message : 'Unable to load app links.';
    } finally {
      if (request === readGeneration) { isLoading = false; render(); }
    }
  }

  async function saveDependencySelection(consumerAppId: string, alias: string, providerAppIds: string[]) {
    const request = workspaceGeneration;
    const key = dependencyKey(consumerAppId, alias);
    if (pendingSelections.has(key)) return;
    const operation = { providerAppIds: [...providerAppIds] };
    pendingSelections.set(key, operation);
    render();
    try {
      const payload = await saveAppDependencySelection(consumerAppId, alias, providerAppIds);
      if (request !== workspaceGeneration || payload.workspace_id !== workspaceId) return;
      // A read started before this acknowledgement must not replace the saved choice.
      readGeneration += 1;
      isLoading = false;
      const previous = dependencies.find(item => item.consumer_app_id === consumerAppId);
      const acknowledged = { ...payload, dependencies: payload.dependencies.map(dependency =>
        dependency.alias === alias ? dependency : previous?.dependencies.find(item => item.alias === dependency.alias) || dependency) };
      dependencies = [...dependencies.filter(item => item.consumer_app_id !== consumerAppId), acknowledged]
        .sort((left, right) => left.consumer_app_id.localeCompare(right.consumer_app_id));
      publishChanged(consumerAppId, acknowledged);
      setNotice({ tone: 'success', message: 'App link updated.' });
    } catch (saveError) {
      if (request === workspaceGeneration) throw saveError;
    } finally {
      if (pendingSelections.get(key) === operation) {
        pendingSelections.delete(key);
        render();
      }
    }
  }

  async function loadDependenciesForWorkspace(workspaceId: string, apps: WorkspaceApp[]) {
    const enabledApps = apps.filter((app) => app.workspace_id === workspaceId && app.status === 'enabled');
    const results: DependencyLoadResult[] = new Array(enabledApps.length);
    let cursor = 0;
    const request = readGeneration;
    await Promise.all(Array.from({ length: Math.min(4, enabledApps.length) }, async () => {
      while (cursor < enabledApps.length && request === readGeneration) {
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
