import { useEffect, useMemo, useRef, useState } from "react";
import { clampPrivateAccessLease } from "@maverick/pwa-cache";
import { AppDependenciesPayload, AppRegistryItem, getAppDependencies } from "../api";
import {
  MAVERICK_IFRAME_SANDBOX,
  appFrameBrowserFeaturePolicy,
  isMaverickFrameMessage,
  isShellWindowMessage,
  postMaverickFrameVisibility,
  postMaverickShellTheme,
  postToMaverickFrame,
  registeredMaverickFrameOwner,
  type MaverickFrameScope,
} from "../iframePolicy";
import { syncAppFrameShellLayout } from "../lib/appFrameShellLayout";
import { externalHttpUrlFromMessage, openExternalUrl } from "../lib/externalUrl";
import type { ShellThemeState } from "../theme";
import { DEFAULT_SHELL_THEME_STATE, shellThemeSignature, urlWithShellThemeSearchParams } from "../theme";
import { ShellPendingIndicator } from "./ShellPendingIndicator";
import { IsolatedMaverickFrame } from "./IsolatedMaverickFrame";
import { StorageFileCacheBroker } from "../storageFileCacheBroker";

type AppFrameParams = Record<string, string | boolean | null>;
const APP_EVENTS_WS_PATH = "/api/apps/events/ws";

type AppReadyMessage = {
  app_id?: string;
  deleted_thread_id?: string;
  detail?: Record<string, unknown>;
  owner_app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
  type?: string;
  url?: unknown;
  workspace_id?: string;
};
type AppEventMessage = {
  detail?: Record<string, unknown>;
  owner_app_id?: string;
  resource?: string;
  type?: string;
  workspace_id?: string;
};
type DependencyCache = Record<string, AppDependenciesPayload>;
const DEPENDENCY_CACHE_STORAGE_KEY = "maverick.baseShell.appDependencies";
const DEPENDENCY_DEBUG_STORAGE_KEY = "maverick.baseShell.debug.dependencies";
const DEPENDENCY_LOG_PREFIX = "[Maverick dependencies]";
const APP_READY_LOAD_FALLBACK_MS = 900;
const APP_PENDING_OVERLAY_DELAY_MS = 140;

export function AppFrameHost({
  activeApp,
  activeAppParams,
  activeWorkspaceId,
  cacheUserId,
  frameScope,
  isMobileLayout,
  onOpenApp,
  sessionExpiresAt,
  shellTheme = DEFAULT_SHELL_THEME_STATE,
}: {
  activeApp: AppRegistryItem;
  activeAppParams: AppFrameParams;
  activeWorkspaceId: string;
  cacheUserId: string;
  frameScope: MaverickFrameScope;
  isMobileLayout: boolean;
  onOpenApp: (appId: string, params?: AppFrameParams) => void;
  sessionExpiresAt: string;
  shellTheme?: ShellThemeState;
}) {
  const mountScopePrefix = `${frameScope.sessionGeneration}:${activeWorkspaceId}:`;
  const activeMountKey = `${mountScopePrefix}${activeApp.app_id}`;
  const [mountedApps, setMountedApps] = useState<Array<{ app: AppRegistryItem; mountKey: string }>>([
    { app: activeApp, mountKey: activeMountKey },
  ]);
  const scopedMountedApps = useMemo(
    () => mountedApps.filter((item) => item.mountKey.startsWith(mountScopePrefix)),
    [mountScopePrefix, mountedApps],
  );
  const [frameRevisions, setFrameRevisions] = useState<Record<string, number>>({});
  const [readyFrames, setReadyFrames] = useState<Record<string, boolean>>(() => ({
    [appFrameInstanceKey(activeMountKey, 0)]: true,
  }));
  const [visibleFrameKey, setVisibleFrameKey] = useState<string | null>(() => appFrameInstanceKey(activeMountKey, 0));
  const [dependencies, setDependencies] = useState<AppDependenciesPayload | null>(null);
  const [dependencyCache, setDependencyCache] = useState<DependencyCache>(() => loadDependencyCache());
  const [showDelayedPendingOverlay, setShowDelayedPendingOverlay] = useState(false);
  const frameRefs = useRef<Record<string, HTMLIFrameElement | null>>({});
  const readyFallbackTimersRef = useRef<Record<string, number>>({});
  const fileCacheBrokerRef = useRef<StorageFileCacheBroker | null>(null);
  const latestNavigationRef = useRef<{ appId: string; params: AppFrameParams }>({
    appId: activeApp.app_id,
    params: activeAppParams,
  });
  const latestDependenciesRef = useRef<AppDependenciesPayload | null>(null);
  const dependencyCacheRef = useRef<DependencyCache>(dependencyCache);
  const frameBootstrapMobileLayoutsRef = useRef<Record<string, boolean>>({});
  const frameBootstrapThemesRef = useRef<Record<string, ShellThemeState>>({});
  const readyDeliveredNavigationSignaturesRef = useRef<Record<string, string>>({});
  const paramsSignature = JSON.stringify(activeAppParams);
  const themeSignature = shellThemeSignature(shellTheme);
  const hasDeclaredDependencies = activeApp.requires.length > 0;
  const activeDependencyCacheKey = dependencyCacheKey(activeWorkspaceId, activeApp.app_id);
  const activeFrameRevision = frameRevisions[activeMountKey] || 0;
  const activeFrameKey = appFrameInstanceKey(activeMountKey, activeFrameRevision);
  const activeFrameReady = Boolean(readyFrames[activeFrameKey]);
  const visibleFrameIsMounted = scopedMountedApps.some(({ mountKey }) => appFrameInstanceKey(mountKey, frameRevisions[mountKey] || 0) === visibleFrameKey);
  const activeFramePending = !activeFrameReady;
  const showPendingState = activeFramePending && (!visibleFrameIsMounted || showDelayedPendingOverlay);

  async function refreshDependencies(appId = activeApp.app_id) {
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
      latestDependenciesRef.current = payload;
      updateDependencyCache(dependencyCacheKey(activeWorkspaceId, appId), payload);
      postDependencies(frameRefs.current[appId], appId, payload);
    } catch (error) {
      logDependencySetup("fetch:error", {
        appId,
        message: error instanceof Error ? error.message : String(error),
      });
      setDependencies(null);
      latestDependenciesRef.current = null;
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
    if (frameScope.workspaceId !== activeWorkspaceId) return undefined;
    const sessionExpiry = Date.parse(sessionExpiresAt);
    const accessLease = Number.isFinite(sessionExpiry)
      ? clampPrivateAccessLease(sessionExpiry) ?? undefined
      : undefined;
    const broker = new StorageFileCacheBroker({
      accessLease,
      principal: {
        appId: "storage",
        userId: cacheUserId,
        workspaceId: activeWorkspaceId,
      },
    });
    fileCacheBrokerRef.current = broker;
    return () => {
      if (fileCacheBrokerRef.current === broker) fileCacheBrokerRef.current = null;
      broker.dispose();
    };
  }, [
    activeWorkspaceId,
    cacheUserId,
    frameScope.sessionGeneration,
    frameScope.workspaceId,
    sessionExpiresAt,
  ]);

  useEffect(() => {
    setMountedApps((current) => {
      const workspaceMountedApps = current.filter((item) => item.mountKey.startsWith(mountScopePrefix));
      if (workspaceMountedApps.some((item) => item.mountKey === activeMountKey)) {
        return workspaceMountedApps.map((item) =>
          item.mountKey === activeMountKey ? { app: activeApp, mountKey: activeMountKey } : item,
        );
      }
      return [...workspaceMountedApps, { app: activeApp, mountKey: activeMountKey }];
    });
  }, [activeApp, activeMountKey, mountScopePrefix]);

  useEffect(() => {
    if (activeFrameReady) {
      setVisibleFrameKey(activeFrameKey);
    } else if (!visibleFrameIsMounted) {
      setVisibleFrameKey(null);
    }
  }, [activeFrameKey, activeFrameReady, visibleFrameIsMounted]);

  useEffect(() => {
    if (!activeFramePending) {
      setShowDelayedPendingOverlay(false);
      return undefined;
    }
    if (!visibleFrameIsMounted) {
      setShowDelayedPendingOverlay(true);
      return undefined;
    }
    setShowDelayedPendingOverlay(false);
    const timer = window.setTimeout(() => {
      setShowDelayedPendingOverlay(true);
    }, APP_PENDING_OVERLAY_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [activeFrameKey, activeFramePending, visibleFrameIsMounted]);

  useEffect(() => {
    const mountedFrameKeys = new Set(
      scopedMountedApps.map(({ mountKey }) => appFrameInstanceKey(mountKey, frameRevisions[mountKey] || 0)),
    );
    setReadyFrames((current) => filterFrameRecord(current, mountedFrameKeys));
    Object.keys(readyDeliveredNavigationSignaturesRef.current).forEach((frameKey) => {
      if (!mountedFrameKeys.has(frameKey)) {
        delete readyDeliveredNavigationSignaturesRef.current[frameKey];
      }
    });
    Object.keys(frameBootstrapThemesRef.current).forEach((frameKey) => {
      if (!mountedFrameKeys.has(frameKey)) {
        delete frameBootstrapThemesRef.current[frameKey];
      }
    });
    Object.keys(frameBootstrapMobileLayoutsRef.current).forEach((frameKey) => {
      if (!mountedFrameKeys.has(frameKey)) {
        delete frameBootstrapMobileLayoutsRef.current[frameKey];
      }
    });
    Object.keys(readyFallbackTimersRef.current).forEach((frameKey) => {
      if (!mountedFrameKeys.has(frameKey)) {
        clearReadyFallbackTimer(frameKey);
      }
    });
  }, [frameRevisions, scopedMountedApps]);

  useEffect(() => {
    latestNavigationRef.current = { appId: activeApp.app_id, params: activeAppParams };
    postMaverickShellTheme(frameRefs.current[activeApp.app_id], shellTheme);
    postNavigation(frameRefs.current[activeApp.app_id], activeApp.app_id, activeAppParams, shellTheme);
    postDependencies(frameRefs.current[activeApp.app_id], activeApp.app_id, latestDependenciesRef.current);
  }, [activeApp.app_id, paramsSignature]);

  useEffect(() => {
    scopedMountedApps.forEach(({ app }) => postMaverickShellTheme(frameRefs.current[app.app_id], shellTheme));
  }, [scopedMountedApps, themeSignature]);

  useEffect(() => {
    scopedMountedApps.forEach(({ app, mountKey }) => {
      const frameKey = appFrameInstanceKey(mountKey, frameRevisions[mountKey] || 0);
      syncAppFrameShellLayout(frameRefs.current[app.app_id], isMobileLayout);
      postMaverickFrameVisibility(frameRefs.current[app.app_id], {
        app_id: app.app_id,
        visible: frameKey === visibleFrameKey,
      });
    });
  }, [frameRevisions, isMobileLayout, scopedMountedApps, visibleFrameKey]);

  useEffect(() => {
    latestDependenciesRef.current = null;
    setDependencies(null);
    if (!hasDeclaredDependencies) {
      logDependencySetup("skip:no-requires", {
        appId: activeApp.app_id,
        workspaceId: activeWorkspaceId,
      });
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
      if (
        !["maverick.app.frontend-changed", "maverick.app.runtime-changed"].includes(event.type || "") ||
        !event.owner_app_id
      ) {
        return;
      }
      window.postMessage(event, window.location.origin);
      const eventMountKey = `${mountScopePrefix}${event.owner_app_id}`;
      setFrameRevisions((current) => ({
        ...current,
        [eventMountKey]: (current[eventMountKey] || 0) + 1,
      }));
    });
  }, [activeWorkspaceId, mountScopePrefix]);

  useEffect(() => {
    function handleAppMessage(event: MessageEvent) {
      const senderOwnerAppId = registeredMaverickFrameOwner(event, frameScope);
      const senderIsShell = isShellWindowMessage(event);
      if (fileCacheBrokerRef.current?.handleWindowMessage(
        event,
        senderOwnerAppId === "storage" ? frameRefs.current.storage ?? null : null,
      )) {
        return;
      }
      const senderFrame = Object.values(frameRefs.current)
        .find((frame) => isMaverickFrameMessage(event, frame));
      if ((!senderOwnerAppId && !senderIsShell) || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as AppReadyMessage;
      if (!payload.type) {
        return;
      }
      if (
        payload.type === "maverick.app.data-changed"
        && payload.owner_app_id
        && (senderIsShell || senderOwnerAppId === payload.owner_app_id)
      ) {
        const ownerFrame = frameRefs.current[payload.owner_app_id];
        if (ownerFrame?.contentWindow && event.source !== ownerFrame.contentWindow) {
          postToMaverickFrame(
            ownerFrame,
            {
              type: "maverick.app.data-changed",
              ...(payload.detail && typeof payload.detail === "object" ? { detail: payload.detail } : {}),
              owner_app_id: payload.owner_app_id,
              resource: payload.resource || "",
              deleted_thread_id: payload.deleted_thread_id || "",
            },
          );
        }
        return;
      }
      const senderIsMountedApp = Boolean(senderFrame);
      if (payload.type === "maverick.app.external-url") {
        if (!senderIsMountedApp) {
          return;
        }
        const url = externalHttpUrlFromMessage(payload.url);
        if (url) {
          openExternalUrl(url);
        }
        return;
      }
      if (!payload.app_id) {
        return;
      }
      if (!senderIsMountedApp) {
        return;
      }
      if (payload.type === "maverick.app.dependencies-changed") {
        const dependencyAppId = payload.app_id;
        getAppDependencies(dependencyAppId)
          .then((nextDependencies) => {
            updateDependencyCache(dependencyCacheKey(activeWorkspaceId, dependencyAppId), nextDependencies);
            if (dependencyAppId === activeApp.app_id) {
              setDependencies(nextDependencies);
              latestDependenciesRef.current = nextDependencies;
            }
            postDependencies(frameRefs.current[dependencyAppId], dependencyAppId, nextDependencies);
          })
          .catch((error) => {
            logDependencySetup("fetch:error", {
              appId: dependencyAppId,
              message: error instanceof Error ? error.message : String(error),
            });
          });
        return;
      }
      if (payload.type === "maverick.app.ready") {
        const frame = frameRefs.current[payload.app_id];
        if (!frame || event.source !== frame.contentWindow) {
          return;
        }
        const frameKey = frameKeyForApp(payload.app_id, scopedMountedApps, frameRevisions);
        if (frameKey) {
          markFrameReady(frameKey);
          if (latestNavigationRef.current.appId === payload.app_id) {
            setVisibleFrameKey(frameKey);
          }
        }
        const latestNavigation = latestNavigationRef.current;
        if (latestNavigation.appId === payload.app_id && frameKey) {
          const navigationSignature = appNavigationSignature(payload.app_id, latestNavigation.params);
          if (readyDeliveredNavigationSignaturesRef.current[frameKey] !== navigationSignature) {
            postMaverickShellTheme(frame, shellTheme);
            if (postNavigation(frame, payload.app_id, latestNavigation.params, shellTheme)) {
              readyDeliveredNavigationSignaturesRef.current[frameKey] = navigationSignature;
            }
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
  }, [frameRevisions, frameScope, onOpenApp, scopedMountedApps]);

  useEffect(() => {
    return () => {
      Object.keys(readyFallbackTimersRef.current).forEach((frameKey) => clearReadyFallbackTimer(frameKey));
    };
  }, []);

  function clearReadyFallbackTimer(frameKey: string) {
    const timer = readyFallbackTimersRef.current[frameKey];
    if (timer !== undefined) {
      window.clearTimeout(timer);
      delete readyFallbackTimersRef.current[frameKey];
    }
  }

  function markFrameReady(frameKey: string) {
    clearReadyFallbackTimer(frameKey);
    setReadyFrames((current) => (current[frameKey] ? current : { ...current, [frameKey]: true }));
  }

  function scheduleFrameReadyFallback(frameKey: string) {
    clearReadyFallbackTimer(frameKey);
    readyFallbackTimersRef.current[frameKey] = window.setTimeout(() => {
      markFrameReady(frameKey);
    }, APP_READY_LOAD_FALLBACK_MS);
  }

  return (
    <section className="bs-workspace-app-panel" aria-label={`${activeApp.name} app`}>
      <div className="bs-workspace-app-surface">
        {scopedMountedApps.map(({ app, mountKey }) => {
          const revision = frameRevisions[mountKey] || 0;
          const frameKey = appFrameInstanceKey(mountKey, revision);
          const isDisplayed = frameKey === visibleFrameKey;
          return (
            <IsolatedMaverickFrame
              allow={appFrameBrowserFeaturePolicy(app.public_app_id || app.app_id)}
              allowFullScreen
              appId={app.app_id}
              frameScope={frameScope}
              aria-hidden={!isDisplayed}
              className={`bs-workspace-app-frame ${isDisplayed ? "is-active" : "is-hidden"}`}
              key={frameKey}
              onLoad={(event) => {
                syncAppFrameShellLayout(event.currentTarget, isMobileLayout);
                postMaverickShellTheme(event.currentTarget, shellTheme);
                postMaverickFrameVisibility(event.currentTarget, {
                  app_id: app.app_id,
                  visible: isDisplayed,
                });
                if (app.app_id === activeApp.app_id) {
                  postNavigation(event.currentTarget, app.app_id, activeAppParams, shellTheme);
                }
                if (!readyFrames[frameKey]) {
                  scheduleFrameReadyFallback(frameKey);
                }
              }}
              ref={(frame) => {
                frameRefs.current[app.app_id] = frame;
              }}
              sandbox={MAVERICK_IFRAME_SANDBOX}
              launchPath={appFrameSrc(
                app.frontend_mount,
                revision,
                bootstrapThemeForFrame(frameBootstrapThemesRef.current, frameKey, shellTheme),
                bootstrapMobileLayoutForFrame(
                  frameBootstrapMobileLayoutsRef.current,
                  frameKey,
                  isMobileLayout,
                ),
              )}
              title={`${app.name} viewport`}
            />
          );
        })}
        {showPendingState ? (
          <div className={`bs-workspace-app-pending ${visibleFrameIsMounted ? "is-over-frame" : "is-empty"}`}>
            <ShellPendingIndicator ariaLabel={`Loading ${activeApp.name}`} label={`Loading ${activeApp.name}`} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function appFrameInstanceKey(mountKey: string, revision: number): string {
  return `${mountKey}:${revision}`;
}

function frameKeyForApp(
  appId: string,
  mountedApps: Array<{ app: AppRegistryItem; mountKey: string }>,
  frameRevisions: Record<string, number>,
): string | null {
  const mountedApp = mountedApps.find(({ app }) => app.app_id === appId);
  if (!mountedApp) {
    return null;
  }
  return appFrameInstanceKey(mountedApp.mountKey, frameRevisions[mountedApp.mountKey] || 0);
}

function filterFrameRecord(current: Record<string, boolean>, mountedFrameKeys: Set<string>): Record<string, boolean> {
  const next = Object.fromEntries(Object.entries(current).filter(([frameKey]) => mountedFrameKeys.has(frameKey)));
  return Object.keys(next).length === Object.keys(current).length ? current : next;
}

function postNavigation(
  frame: HTMLIFrameElement | null | undefined,
  appId: string,
  params: AppFrameParams,
  shellTheme: ShellThemeState,
): boolean {
  if (!frame?.contentWindow) {
    return false;
  }
  postToMaverickFrame(
    frame,
    {
      type: "maverick.app.navigate",
      app_id: appId,
      params: normalizeParams(params),
      theme: shellTheme,
    },
  );
  return true;
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

function appFrameSrc(
  frontendMount: string,
  revision: number,
  shellTheme: ShellThemeState,
  isMobileLayout: boolean,
): string {
  const themedUrl = urlWithShellThemeSearchParams(frontendMount, shellTheme);
  themedUrl.searchParams.set("maverick_mobile_layout", isMobileLayout ? "1" : "0");
  const themedMount = `${themedUrl.pathname}${themedUrl.search}${themedUrl.hash}`;
  if (revision <= 0) {
    return themedMount;
  }
  return mountUrlWithParam(themedMount, "_maverick_refresh", String(revision));
}

function bootstrapThemeForFrame(
  themesByFrameKey: Record<string, ShellThemeState>,
  frameKey: string,
  shellTheme: ShellThemeState,
): ShellThemeState {
  themesByFrameKey[frameKey] = themesByFrameKey[frameKey] || shellTheme;
  return themesByFrameKey[frameKey];
}

function bootstrapMobileLayoutForFrame(
  layoutsByFrameKey: Record<string, boolean>,
  frameKey: string,
  isMobileLayout: boolean,
): boolean {
  if (!(frameKey in layoutsByFrameKey)) layoutsByFrameKey[frameKey] = isMobileLayout;
  return layoutsByFrameKey[frameKey];
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
