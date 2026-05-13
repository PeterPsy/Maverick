import { useEffect, useRef, useState } from "react";
import { AppDependenciesPayload, AppRegistryItem, getAppDependencies, saveAppDependencySelection } from "../api";
import { MAVERICK_IFRAME_SANDBOX, postMaverickFrameVisibility, postToMaverickFrame } from "../iframePolicy";
import { syncAppFrameShellLayout } from "../lib/appFrameShellLayout";
import { AppDependencySetup } from "./AppDependencySetup";

type AppFrameParams = Record<string, string | boolean | null>;
const APP_EVENTS_WS_PATH = "/api/apps/events/ws";

type AppReadyMessage = {
  app_id?: string;
  deleted_thread_id?: string;
  owner_app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
  type?: string;
  workspace_id?: string;
};
type AppEventMessage = {
  owner_app_id?: string;
  resource?: string;
  type?: string;
  workspace_id?: string;
};
type DependencyCache = Record<string, AppDependenciesPayload>;
const DEPENDENCY_CACHE_STORAGE_KEY = "maverick.baseShell.appDependencies";
const DEPENDENCY_DEBUG_STORAGE_KEY = "maverick.baseShell.debug.dependencies";
const DEPENDENCY_LOG_PREFIX = "[Maverick dependencies]";

export function AppFrameHost({
  activeApp,
  activeAppParams,
  activeWorkspaceId,
  isMobileLayout,
  onOpenApp,
}: {
  activeApp: AppRegistryItem;
  activeAppParams: AppFrameParams;
  activeWorkspaceId: string;
  isMobileLayout: boolean;
  onOpenApp: (appId: string, params?: AppFrameParams) => void;
}) {
  const activeMountKey = `${activeWorkspaceId}:${activeApp.app_id}`;
  const [mountedApps, setMountedApps] = useState<Array<{ app: AppRegistryItem; mountKey: string }>>([
    { app: activeApp, mountKey: activeMountKey },
  ]);
  const [frameRevisions, setFrameRevisions] = useState<Record<string, number>>({});
  const [dependencies, setDependencies] = useState<AppDependenciesPayload | null>(null);
  const [dependencyCache, setDependencyCache] = useState<DependencyCache>(() => loadDependencyCache());
  const [dependencyError, setDependencyError] = useState<string | null>(null);
  const [isDependencyPanelOpen, setIsDependencyPanelOpen] = useState(false);
  const [isDependencyLoading, setIsDependencyLoading] = useState(false);
  const frameRefs = useRef<Record<string, HTMLIFrameElement | null>>({});
  const latestNavigationRef = useRef<{ appId: string; params: AppFrameParams }>({
    appId: activeApp.app_id,
    params: activeAppParams,
  });
  const latestDependenciesRef = useRef<AppDependenciesPayload | null>(null);
  const dependencyCacheRef = useRef<DependencyCache>(dependencyCache);
  const readyNavigationSignaturesRef = useRef<Record<string, string>>({});
  const paramsSignature = JSON.stringify(activeAppParams);
  const hasDeclaredDependencies = activeApp.requires.length > 0;
  const dependencyStatus = dependencyError ? "error" : dependencies?.status || (isDependencyLoading ? "loading" : "unknown");
  const activeDependencyCacheKey = dependencyCacheKey(activeWorkspaceId, activeApp.app_id);

  async function refreshDependencies(appId = activeApp.app_id) {
    setIsDependencyLoading(true);
    logDependencySetup("fetch:start", {
      appId,
      cacheKey: dependencyCacheKey(activeWorkspaceId, appId),
      workspaceId: activeWorkspaceId,
    });
    try {
      const payload = await getAppDependencies(appId);
      logDependencySetup("fetch:success", {
        appId,
        status: payload.status,
        dependencyCount: payload.dependencies.length,
      });
      setDependencies(payload);
      setDependencyError(null);
      latestDependenciesRef.current = payload;
      updateDependencyCache(dependencyCacheKey(activeWorkspaceId, appId), payload);
      postDependencies(frameRefs.current[appId], appId, payload);
    } catch (error) {
      logDependencySetup("fetch:error", {
        appId,
        message: error instanceof Error ? error.message : String(error),
      });
      setDependencies(null);
      setDependencyError(error instanceof Error ? error.message : "Dependency setup failed.");
      latestDependenciesRef.current = null;
    } finally {
      setIsDependencyLoading(false);
    }
  }

  function updateDependencyCache(cacheKey: string, payload: AppDependenciesPayload) {
    setDependencyCache((current) => {
      const next = { ...current };
      if (payload.status === "resolved") {
        next[cacheKey] = payload;
        logDependencySetup("cache:save", {
          cacheKey,
          consumerAppId: payload.consumer_app_id,
          dependencyCount: payload.dependencies.length,
        });
      } else {
        delete next[cacheKey];
        logDependencySetup("cache:delete", {
          cacheKey,
          consumerAppId: payload.consumer_app_id,
          status: payload.status,
        });
      }
      dependencyCacheRef.current = next;
      saveDependencyCache(next);
      return next;
    });
  }

  useEffect(() => {
    dependencyCacheRef.current = dependencyCache;
  }, [dependencyCache]);

  useEffect(() => {
    setMountedApps((current) => {
      const workspaceMountedApps = current.filter((item) => item.mountKey.startsWith(`${activeWorkspaceId}:`));
      if (workspaceMountedApps.some((item) => item.mountKey === activeMountKey)) {
        return workspaceMountedApps.map((item) =>
          item.mountKey === activeMountKey ? { app: activeApp, mountKey: activeMountKey } : item,
        );
      }
      return [...workspaceMountedApps, { app: activeApp, mountKey: activeMountKey }];
    });
  }, [activeApp, activeMountKey, activeWorkspaceId]);

  useEffect(() => {
    latestNavigationRef.current = { appId: activeApp.app_id, params: activeAppParams };
    postNavigation(frameRefs.current[activeApp.app_id], activeApp.app_id, activeAppParams);
    readyNavigationSignaturesRef.current[activeApp.app_id] = appNavigationSignature(activeApp.app_id, activeAppParams);
    postDependencies(frameRefs.current[activeApp.app_id], activeApp.app_id, latestDependenciesRef.current);
  }, [activeApp.app_id, paramsSignature]);

  useEffect(() => {
    mountedApps.forEach(({ app }) => {
      syncAppFrameShellLayout(frameRefs.current[app.app_id], isMobileLayout);
      postMaverickFrameVisibility(frameRefs.current[app.app_id], {
        app_id: app.app_id,
        visible: app.app_id === activeApp.app_id,
      });
    });
  }, [activeApp.app_id, isMobileLayout, mountedApps]);

  useEffect(() => {
    latestDependenciesRef.current = null;
    setDependencies(null);
    setDependencyError(null);
    setIsDependencyPanelOpen(false);
    if (!hasDeclaredDependencies) {
      logDependencySetup("skip:no-requires", {
        appId: activeApp.app_id,
        workspaceId: activeWorkspaceId,
      });
      setIsDependencyLoading(false);
      return;
    }
    const cached = dependencyCacheRef.current[activeDependencyCacheKey] || null;
    if (cached) {
      logDependencySetup("cache:hit", {
        appId: activeApp.app_id,
        cacheKey: activeDependencyCacheKey,
        dependencyCount: cached.dependencies.length,
      });
      setDependencies(cached);
      latestDependenciesRef.current = cached;
      setIsDependencyLoading(false);
      postDependencies(frameRefs.current[activeApp.app_id], activeApp.app_id, cached);
      return;
    }
    logDependencySetup("cache:miss", {
      appId: activeApp.app_id,
      cacheKey: activeDependencyCacheKey,
      cacheKeys: Object.keys(dependencyCacheRef.current),
    });
    refreshDependencies(activeApp.app_id);
  }, [activeApp.app_id, activeDependencyCacheKey, hasDeclaredDependencies]);

  useEffect(() => {
    return connectAppEventSocket((event) => {
      if (event.workspace_id && event.workspace_id !== activeWorkspaceId) {
        return;
      }
      if (event.type === "maverick.app.data-changed" && event.owner_app_id) {
        window.postMessage(event, window.location.origin);
        return;
      }
      if (event.type !== "maverick.app.frontend-changed" || !event.owner_app_id) {
        return;
      }
      window.postMessage(event, window.location.origin);
      const eventMountKey = `${activeWorkspaceId}:${event.owner_app_id}`;
      delete readyNavigationSignaturesRef.current[event.owner_app_id];
      setFrameRevisions((current) => ({
        ...current,
        [eventMountKey]: (current[eventMountKey] || 0) + 1,
      }));
    });
  }, [activeWorkspaceId]);

  useEffect(() => {
    function handleAppMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as AppReadyMessage;
      if (!payload.type) {
        return;
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id) {
        const ownerFrame = frameRefs.current[payload.owner_app_id];
        if (ownerFrame?.contentWindow && event.source !== ownerFrame.contentWindow) {
          postToMaverickFrame(
            ownerFrame,
            {
              type: "maverick.app.data-changed",
              owner_app_id: payload.owner_app_id,
              resource: payload.resource || "",
              deleted_thread_id: payload.deleted_thread_id || "",
            },
          );
        }
        return;
      }
      if (!payload.app_id) {
        return;
      }
      const senderIsMountedApp = Object.values(frameRefs.current).some((frame) => frame?.contentWindow === event.source);
      if (!senderIsMountedApp) {
        return;
      }
      if (payload.type === "maverick.app.ready") {
        const frame = frameRefs.current[payload.app_id];
        if (!frame || event.source !== frame.contentWindow) {
          return;
        }
        const latestNavigation = latestNavigationRef.current;
        if (latestNavigation.appId === payload.app_id) {
          const navigationSignature = appNavigationSignature(payload.app_id, latestNavigation.params);
          if (readyNavigationSignaturesRef.current[payload.app_id] !== navigationSignature) {
            postNavigation(frame, payload.app_id, latestNavigation.params);
            readyNavigationSignaturesRef.current[payload.app_id] = navigationSignature;
          }
          postDependencies(frame, payload.app_id, latestDependenciesRef.current);
        }
      }
      if (payload.type === "maverick.app.open-app") {
        onOpenApp(payload.app_id, {
          ...(payload.params || {}),
          workspace_id: payload.workspace_id || payload.params?.workspace_id || null,
        });
      }
    }

    window.addEventListener("message", handleAppMessage);
    return () => window.removeEventListener("message", handleAppMessage);
  }, [onOpenApp]);

  return (
    <section className="bs-workspace-app-panel" aria-label={`${activeApp.name} app`}>
      <div className="bs-workspace-app-surface">
        {hasDeclaredDependencies ? (
          <button
            aria-label="Configura collegamenti app"
            className={`bs-dependency-launcher is-${dependencyStatus}`}
            onClick={() => {
              logDependencySetup("panel:open", {
                appId: activeApp.app_id,
                status: dependencyStatus,
                hasDependencies: Boolean(dependencies),
                hasError: Boolean(dependencyError),
              });
              setIsDependencyPanelOpen(true);
              if (!isDependencyLoading && (!dependencies || dependencyError)) {
                refreshDependencies(activeApp.app_id);
              }
            }}
            title="Configura collegamenti app"
            type="button"
          >
            <span className="material-symbols-rounded" aria-hidden="true">hub</span>
          </button>
        ) : null}
        {mountedApps.map(({ app, mountKey }) => {
          const isActive = app.app_id === activeApp.app_id;
          const revision = frameRevisions[mountKey] || 0;
          return (
            <iframe
              aria-hidden={!isActive}
              className={`bs-workspace-app-frame ${isActive ? "is-active" : "is-hidden"}`}
              key={`${mountKey}:${revision}`}
              onLoad={(event) => {
                syncAppFrameShellLayout(event.currentTarget, isMobileLayout);
                postMaverickFrameVisibility(event.currentTarget, {
                  app_id: app.app_id,
                  visible: isActive,
                });
                if (app.app_id === activeApp.app_id) {
                  postNavigation(event.currentTarget, app.app_id, activeAppParams);
                  readyNavigationSignaturesRef.current[app.app_id] = appNavigationSignature(app.app_id, activeAppParams);
                }
              }}
              ref={(frame) => {
                frameRefs.current[app.app_id] = frame;
              }}
              sandbox={MAVERICK_IFRAME_SANDBOX}
              src={appFrameSrc(app.frontend_mount, revision)}
              title={`${app.name} viewport`}
            />
          );
        })}
        {hasDeclaredDependencies ? (
          <AppDependencySetup
            dependencies={dependencies}
            error={dependencyError}
            isLoading={isDependencyLoading}
            isOpen={isDependencyPanelOpen}
            onClose={() => setIsDependencyPanelOpen(false)}
            onOpenAppStore={(interfaceId) => onOpenApp("app-store", { interface_filter: interfaceId })}
            onSave={async (alias, providerAppIds) => {
              logDependencySetup("selection:save:start", {
                appId: activeApp.app_id,
                alias,
                providerAppIds,
              });
              const payload = await saveAppDependencySelection(activeApp.app_id, alias, providerAppIds);
              logDependencySetup("selection:save:success", {
                appId: activeApp.app_id,
                alias,
                status: payload.status,
              });
              setDependencies(payload);
              latestDependenciesRef.current = payload;
              updateDependencyCache(activeDependencyCacheKey, payload);
              postDependencies(frameRefs.current[activeApp.app_id], activeApp.app_id, payload);
            }}
          />
        ) : null}
      </div>
    </section>
  );
}

function postNavigation(frame: HTMLIFrameElement | null | undefined, appId: string, params: AppFrameParams) {
  if (!frame?.contentWindow) {
    return;
  }
  postToMaverickFrame(
    frame,
    {
      type: "maverick.app.navigate",
      app_id: appId,
      params: normalizeParams(params),
    },
  );
}

function postDependencies(
  frame: HTMLIFrameElement | null | undefined,
  appId: string,
  dependencies: AppDependenciesPayload | null,
) {
  if (!frame?.contentWindow || !dependencies) {
    return;
  }
  postToMaverickFrame(
    frame,
    {
      type: "maverick.app.dependencies",
      app_id: appId,
      dependencies,
    },
  );
}

function appNavigationSignature(appId: string, params: AppFrameParams): string {
  return JSON.stringify({ app_id: appId, params: normalizeParams(params) });
}

function normalizeParams(params: AppFrameParams): Record<string, string | boolean> {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== null && value !== undefined && value !== false),
  ) as Record<string, string | boolean>;
}

function appFrameSrc(frontendMount: string, revision: number): string {
  if (revision <= 0) {
    return frontendMount;
  }
  return mountUrlWithParam(frontendMount, "_maverick_refresh", String(revision));
}

function mountUrlWithParam(frontendMount: string, name: string, value: string): string {
  const url = new URL(frontendMount, window.location.origin);
  url.searchParams.set(name, value);
  return `${url.pathname}${url.search}${url.hash}`;
}

function dependencyCacheKey(workspaceId: string, appId: string): string {
  return `${workspaceId}:${appId}`;
}

function logDependencySetup(message: string, context: Record<string, unknown> = {}) {
  if (typeof console === "undefined") {
    return;
  }
  try {
    if (window.localStorage.getItem(DEPENDENCY_DEBUG_STORAGE_KEY) !== "1") {
      return;
    }
    console.info(DEPENDENCY_LOG_PREFIX, message, context);
  } catch {
    return;
  }
}

function loadDependencyCache(): DependencyCache {
  if (typeof window === "undefined") {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(DEPENDENCY_CACHE_STORAGE_KEY);
    const value = raw ? JSON.parse(raw) : {};
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(value).filter(([, payload]) => isResolvedDependencyPayload(payload)),
    ) as DependencyCache;
  } catch {
    return {};
  }
}

function saveDependencyCache(cache: DependencyCache) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(DEPENDENCY_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    return;
  }
}

function isResolvedDependencyPayload(value: unknown): value is AppDependenciesPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const payload = value as Partial<AppDependenciesPayload>;
  return payload.status === "resolved" && typeof payload.consumer_app_id === "string" && Array.isArray(payload.dependencies);
}

function connectAppEventSocket(onEvent: (event: AppEventMessage) => void): () => void {
  if (typeof WebSocket === "undefined") {
    return () => {};
  }
  let socket: WebSocket | null = null;
  let reconnectTimer: number | undefined;
  let closed = false;

  function connect() {
    socket = new WebSocket(appEventSocketUrl());
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as AppEventMessage;
        onEvent(event);
      } catch {
        return;
      }
    };
    socket.onclose = () => {
      if (!closed) {
        reconnectTimer = window.setTimeout(connect, 1000);
      }
    };
    socket.onerror = () => {
      socket?.close();
    };
  }

  connect();
  return () => {
    closed = true;
    if (reconnectTimer !== undefined) {
      window.clearTimeout(reconnectTimer);
    }
    socket?.close();
  };
}

function appEventSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${APP_EVENTS_WS_PATH}`;
}
