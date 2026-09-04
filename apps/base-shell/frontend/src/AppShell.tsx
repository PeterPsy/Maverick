import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  AppRegistryItem,
  configureActiveProvider,
  getProviderSetupSettings,
  getSession,
  listApps,
  listPinnedApps,
  listWorkspaces,
  logout,
  MaverickHttpError,
  ProviderSetupSettings,
  savePinnedApps,
  SessionPayload,
  switchWorkspace,
  WorkspaceItem,
} from "./api";
import {
  CHAT_APP_ID,
  currentShellAppRoute,
  initialShellLaunchRoute,
  isInitialChatLaunchRoute,
  newChatRouteParams,
  preferredActiveApp,
  pushShellAppRoute,
  replaceShellAppRoute,
  resolveAppOpenParams,
  SETTINGS_APP_ID,
  shellAppRailApps,
  shellVisibleApps,
} from "./navigation";
import { clampFloatingChatWidth, clampSidebarDetailsWidth, readShellSession, resolveInitialSidebarOpen, writeShellSession } from "./session";
import type { FloatingChatMode, SidebarMode } from "./session";
import { applyShellThemeToDocument, createShellThemeState, readSystemColorScheme } from "./theme";
import type { ShellEffectiveTheme, ShellThemeMode } from "./theme";
import { markStartupMetric, measureStartupMetric } from "./startupMetrics";
import { getInitialMobileLayout, useMobileLayout } from "./hooks/useMobileLayout";
import {
  runShellRead,
  shellCacheLifecycle,
  shellCachePrincipal,
  shellRetryCoordinator,
} from "./pwaCacheRuntime";
import { useSidebarRailMetrics } from "./hooks/useSidebarRailMetrics";
import {
  isMaverickOwnerMessage,
  isRegisteredMaverickFrameMessage,
  isShellWindowMessage,
  type MaverickFrameScope,
} from "./iframePolicy";
import { usePwaDataCacheBrokerHost } from "./usePwaDataCacheBrokerHost";
import { FloatingChatHost } from "./components/FloatingChatHost";
import { LoginScreen } from "./components/LoginScreen";
import { MobileShellHeader } from "./components/MobileShellHeader";
import { MobilePinnedAppsPanel } from "./components/MobilePinnedAppsPanel";
import { Sidebar } from "./components/Sidebar";
import { ProviderSetupDialog } from "./components/ProviderSetupDialog";
import { ShellPendingIndicator } from "./components/ShellPendingIndicator";
import { WorkspaceView } from "./components/WorkspaceView";
import type { WidgetPrimaryActionState } from "./components/WidgetSlot";

const MOBILE_SIDEBAR_TRANSITION_MS = 220;
const MOBILE_CHAT_TRANSITION_MS = 240;

export function AppShell() {
  const initialSession = useMemo(() => readShellSession(), []);
  const initialRoute = useMemo(() => currentShellAppRoute(), []);
  const isInitialChatLaunch = useMemo(() => isInitialChatLaunchRoute(initialRoute), [initialRoute]);
  const initialLaunchRoute = useMemo(() => initialShellLaunchRoute(initialRoute), [initialRoute]);
  const initialIsMobileLayout = useMemo(() => getInitialMobileLayout(), []);
  const initialActiveAppId = initialLaunchRoute.appId || initialSession.activeAppId;
  const [apps, setApps] = useState<AppRegistryItem[]>([]);
  const [pinnedAppIds, setPinnedAppIds] = useState<string[]>(["chat"]);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [settings, setSettings] = useState<ProviderSetupSettings | null>(null);
  const [activeAppId, setActiveAppId] = useState<string | null>(initialActiveAppId);
  const [activeAppParams, setActiveAppParams] = useState<Record<string, string | boolean | null>>(initialLaunchRoute.params);
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>(isInitialChatLaunch ? "rail" : initialSession.sidebarMode);
  const [sidebarDetailsWidthPx, setSidebarDetailsWidthPx] = useState(() => clampSidebarDetailsWidth(initialSession.sidebarDetailsWidthPx));
  const [floatingChatMode, setFloatingChatMode] = useState<FloatingChatMode>(initialSession.floatingChatMode);
  const [floatingChatWidthPx, setFloatingChatWidthPx] = useState(() => clampFloatingChatWidth(initialSession.floatingChatWidthPx));
  const [floatingChatThreadId, setFloatingChatThreadId] = useState<string | null>(initialSession.floatingChatThreadId);
  const [floatingChatNavigationScope, setFloatingChatNavigationScope] = useState<string | null>(initialSession.floatingChatNavigationScope);
  const [themeMode, setThemeMode] = useState<ShellThemeMode>(initialSession.themeMode);
  const [systemColorScheme, setSystemColorScheme] = useState<ShellEffectiveTheme>(() => readSystemColorScheme());
  const [isSidebarOpen, setIsSidebarOpen] = useState(() =>
    resolveInitialSidebarOpen(initialSession, {
      isInitialChatLaunch,
      isMobileLayout: initialIsMobileLayout,
    }),
  );
  const [isMobilePinnedAppsOpen, setIsMobilePinnedAppsOpen] = useState(false);
  const [isMobileChatOpen, setIsMobileChatOpen] = useState(false);
  const [isMobileChatClosing, setIsMobileChatClosing] = useState(false);
  const [isSidebarClosing, setIsSidebarClosing] = useState(false);
  const [isSidebarResizing, setIsSidebarResizing] = useState(false);
  const [isFloatingChatResizing, setIsFloatingChatResizing] = useState(false);
  const [dismissedProviderSetupWorkspaceId, setDismissedProviderSetupWorkspaceId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isWorkspacesLoading, setIsWorkspacesLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mobilePrimaryAction, setMobilePrimaryAction] = useState<WidgetPrimaryActionState>({
    available: false,
    label: "",
    preferredSurface: "app",
  });
  const [mobilePrimaryActionRequestId, setMobilePrimaryActionRequestId] = useState(0);
  const isMobileLayout = useMobileLayout();
  const isSidebarPinned = sidebarMode === "fixed" && !isMobileLayout;
  const isChatAppActive = activeAppId === CHAT_APP_ID;
  const isFloatingChatFixed = floatingChatMode === "fixed-right" && !isMobileLayout && !isChatAppActive;
  const sidebarCloseTimerRef = useRef<number | null>(null);
  const mobileChatCloseTimerRef = useRef<number | null>(null);
  const pinnedAppIdsRef = useRef(pinnedAppIds);
  const pinnedAppsSaveVersionRef = useRef(0);
  const persistedPinnedAppIdsRef = useRef(pinnedAppIds);
  const persistedPinnedAppsVersionRef = useRef(0);
  const shellLoadVersionRef = useRef(0);
  const shellLoadAbortRef = useRef<AbortController | null>(null);
  const shellLoadInFlightRef = useRef(false);
  const authenticatedFrameScopeIdentity = session?.authenticated
    ? JSON.stringify([session.user.user_id, session.workspace_id, session.expires_at])
    : null;
  const authenticatedFrameWorkspaceId = session?.authenticated ? session.workspace_id : null;
  const frameScope = useMemo<MaverickFrameScope | null>(() => (
    authenticatedFrameScopeIdentity && authenticatedFrameWorkspaceId
      ? Object.freeze({
          sessionGeneration: crypto.randomUUID(),
          workspaceId: authenticatedFrameWorkspaceId,
        })
      : null
  ), [authenticatedFrameScopeIdentity, authenticatedFrameWorkspaceId]);
  const cancelShellLoading = useCallback(({ resetRecovery = false } = {}) => {
    shellLoadAbortRef.current?.abort();
    shellLoadAbortRef.current = null;
    shellLoadInFlightRef.current = false;
    shellLoadVersionRef.current += 1;
    if (resetRecovery) {
      shellRetryCoordinator.cancelAll("Base Shell scope reset.");
    }
  }, []);
  const clearShellUiAfterAuthorizationFailure = useCallback(() => {
    setSession({ authenticated: false });
    setApps([]);
    setWorkspaces([]);
    setSettings(null);
    setError(null);
    setIsLoading(false);
    setIsWorkspacesLoading(false);
  }, []);
  const handleEmbeddedAuthorizationFailure = useCallback(() => {
    cancelShellLoading({ resetRecovery: true });
    clearShellUiAfterAuthorizationFailure();
  }, [cancelShellLoading, clearShellUiAfterAuthorizationFailure]);
  usePwaDataCacheBrokerHost({
    appRegistry: apps,
    frameScope,
    onAuthorizationFailure: handleEmbeddedAuthorizationFailure,
    principal: session?.authenticated ? {
      sessionExpiresAt: session.expires_at,
      userId: session.user.user_id,
      workspaceId: session.workspace_id,
    } : null,
  });
  const railApps = shellAppRailApps(apps, pinnedAppIds);
  const settingsShortcutApp = shellVisibleApps(apps).find((app) => app.app_id === SETTINGS_APP_ID) ?? null;
  const hasSettingsShortcut = Boolean(settingsShortcutApp);
  const shellRailItemCount = isLoading && railApps.length === 0 ? 4 : railApps.length + (hasSettingsShortcut ? 1 : 0);
  const shellSidebarMetrics = useSidebarRailMetrics(shellRailItemCount, isMobileLayout);
  const shellTheme = useMemo(() => createShellThemeState(themeMode, systemColorScheme), [systemColorScheme, themeMode]);
  const shellStyle = useMemo(() => {
    const style: CSSProperties & {
      "--bs-floating-chat-fixed-space"?: string;
      "--bs-floating-chat-width"?: string;
      "--maverick-sidebar-details-width"?: string;
    } = { ...shellSidebarMetrics };
    if (!isMobileLayout) {
      style["--maverick-sidebar-details-width"] = `${sidebarDetailsWidthPx}px`;
      style["--bs-floating-chat-width"] = `${floatingChatWidthPx}px`;
      style["--bs-floating-chat-fixed-space"] = `${floatingChatWidthPx + 24}px`;
    }
    return style;
  }, [floatingChatWidthPx, isMobileLayout, shellSidebarMetrics, sidebarDetailsWidthPx]);

  function clearSidebarClosing() {
    if (sidebarCloseTimerRef.current !== null) {
      window.clearTimeout(sidebarCloseTimerRef.current);
      sidebarCloseTimerRef.current = null;
    }
    setIsSidebarClosing(false);
  }

  function clearMobileChatClosing() {
    if (mobileChatCloseTimerRef.current !== null) {
      window.clearTimeout(mobileChatCloseTimerRef.current);
      mobileChatCloseTimerRef.current = null;
    }
    setIsMobileChatClosing(false);
  }

  function openSidebar() {
    closeMobileChatPanel();
    clearSidebarClosing();
    setIsMobilePinnedAppsOpen(false);
    setIsSidebarOpen(true);
  }

  function closeSidebar() {
    if (isSidebarPinned) {
      clearSidebarClosing();
      setIsSidebarOpen(true);
      return;
    }
    if (isMobileLayout && isSidebarOpen) {
      clearSidebarClosing();
      setIsSidebarClosing(true);
      sidebarCloseTimerRef.current = window.setTimeout(() => {
        setIsSidebarClosing(false);
        sidebarCloseTimerRef.current = null;
      }, MOBILE_SIDEBAR_TRANSITION_MS);
    }
    setIsSidebarOpen(false);
  }

  function toggleMobileSidebar() {
    if (isSidebarOpen) {
      closeSidebar();
      return;
    }
    openSidebar();
  }

  function toggleMobilePinnedApps() {
    if (isMobilePinnedAppsOpen) {
      setIsMobilePinnedAppsOpen(false);
      return;
    }
    closeMobileChatPanel();
    closeSidebar();
    setIsMobilePinnedAppsOpen(true);
  }

  function openMobileChatPanel() {
    clearMobileChatClosing();
    closeSidebar();
    setIsMobilePinnedAppsOpen(false);
    setIsMobileChatOpen(true);
  }

  function closeMobileChatPanel() {
    if (!isMobileLayout) {
      clearMobileChatClosing();
      setIsMobileChatOpen(false);
      return;
    }
    if (isMobileChatOpen) {
      clearMobileChatClosing();
      setIsMobileChatClosing(true);
      mobileChatCloseTimerRef.current = window.setTimeout(() => {
        setIsMobileChatClosing(false);
        mobileChatCloseTimerRef.current = null;
      }, MOBILE_CHAT_TRANSITION_MS);
    }
    setIsMobileChatOpen(false);
  }

  function notifyAppDataChanged(ownerAppId: string, resource: string, detail: Record<string, string> = {}) {
    window.postMessage(
      {
        type: "maverick.app.data-changed",
        owner_app_id: ownerAppId,
        resource,
        ...detail,
      },
      window.location.origin,
    );
  }

  async function clearShellAfterAuthorizationFailure(controller: AbortController) {
    controller.abort();
    await shellCacheLifecycle.authorizationFailure().catch(() => undefined);
    clearShellUiAfterAuthorizationFailure();
  }

  async function loadShellState() {
    if (shellLoadInFlightRef.current) {
      return;
    }
    shellLoadAbortRef.current?.abort();
    const controller = new AbortController();
    shellLoadAbortRef.current = controller;
    shellLoadInFlightRef.current = true;
    const deferredLoads: Promise<void>[] = [];
    const loadVersion = shellLoadVersionRef.current + 1;
    shellLoadVersionRef.current = loadVersion;
    const loadStartedAt = performance.now();
    markStartupMetric("shell.bootstrap.start");
    setIsLoading(true);
    setIsWorkspacesLoading(true);
    try {
      const sessionStartedAt = performance.now();
      const currentSession = await runShellRead(
        "base-shell:session",
        (signal) => getSession(signal),
        controller.signal,
      );
      measureStartupMetric("shell.bootstrap.session", sessionStartedAt, { authenticated: currentSession.authenticated });
      if (shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      setSession(currentSession);
      if (!currentSession.authenticated) {
        await shellCacheLifecycle.authorizationFailure().catch(() => undefined);
        setApps([]);
        setWorkspaces([]);
        setSettings(null);
        setError(null);
        setIsWorkspacesLoading(false);
        measureStartupMetric("shell.bootstrap.total", loadStartedAt, { authenticated: false });
        return;
      }
      await shellCacheLifecycle.transition(shellCachePrincipal(currentSession));
      deferredLoads.push(
        loadWorkspaceState(loadVersion, controller.signal),
        loadProviderSetupState(loadVersion, controller.signal),
      );
      const blockingStartedAt = performance.now();
      const registry = await runShellRead(
        "base-shell:app-registry",
        (signal) => listApps(signal),
        controller.signal,
      );
      if (shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      setApps(registry.items);
      setError(null);
      measureStartupMetric("shell.bootstrap.blocking_payloads", blockingStartedAt, {
        app_count: registry.items.length,
      });
      measureStartupMetric("shell.bootstrap.total", loadStartedAt, { authenticated: true });
      deferredLoads.push(loadPinnedAppsState(loadVersion, controller.signal));
    } catch (loadError) {
      if (shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      if (controller.signal.aborted) {
        return;
      }
      if (loadError instanceof MaverickHttpError && [401, 403].includes(loadError.status)) {
        await clearShellAfterAuthorizationFailure(controller);
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "Errore sconosciuto.");
      measureStartupMetric("shell.bootstrap.error", loadStartedAt, {
        message: loadError instanceof Error ? loadError.message : "unknown",
      });
    } finally {
      if (shellLoadAbortRef.current === controller) {
        shellLoadInFlightRef.current = false;
      }
      const releaseController = () => {
        if (shellLoadAbortRef.current === controller) {
          shellLoadAbortRef.current = null;
        }
      };
      if (deferredLoads.length > 0) {
        void Promise.allSettled(deferredLoads).then(releaseController);
      } else {
        releaseController();
      }
      if (shellLoadVersionRef.current === loadVersion) {
        setIsLoading(false);
      }
    }
  }

  async function loadWorkspaceState(loadVersion: number, signal?: AbortSignal) {
    const deferredStartedAt = performance.now();
    try {
      const workspacePayload = signal
        ? await runShellRead("base-shell:workspaces", (retrySignal) => listWorkspaces(retrySignal), signal)
        : await listWorkspaces();
      if (signal?.aborted || shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      setWorkspaces(workspacePayload.items);
      measureStartupMetric("shell.bootstrap.deferred_payloads", deferredStartedAt, {
        resource: "workspaces",
        workspace_count: workspacePayload.items.length,
      });
    } catch (loadError) {
      if (signal?.aborted || shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      measureStartupMetric("shell.bootstrap.deferred_error", deferredStartedAt, {
        message: loadError instanceof Error ? loadError.message : "unknown",
        resource: "workspaces",
      });
    } finally {
      if (shellLoadVersionRef.current === loadVersion) {
        setIsWorkspacesLoading(false);
      }
    }
  }

  async function loadProviderSetupState(loadVersion: number, signal?: AbortSignal) {
    const deferredStartedAt = performance.now();
    try {
      const providerSetupSettings = signal
        ? await runShellRead("base-shell:provider-setup", (retrySignal) => getProviderSetupSettings(retrySignal), signal)
        : await getProviderSetupSettings();
      if (signal?.aborted || shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      setSettings(providerSetupSettings);
      measureStartupMetric("shell.bootstrap.deferred_payloads", deferredStartedAt, {
        resource: "provider_setup",
      });
    } catch (loadError) {
      if (signal?.aborted || shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      measureStartupMetric("shell.bootstrap.deferred_error", deferredStartedAt, {
        message: loadError instanceof Error ? loadError.message : "unknown",
        resource: "provider_setup",
      });
    }
  }

  async function loadPinnedAppsState(loadVersion: number, signal?: AbortSignal) {
    const deferredStartedAt = performance.now();
    const pinnedStateVersion = pinnedAppsSaveVersionRef.current;
    try {
      const pinnedApps = signal
        ? await runShellRead("base-shell:pinned-apps", (retrySignal) => listPinnedApps(retrySignal), signal)
        : await listPinnedApps();
      if (
        signal?.aborted
        || shellLoadVersionRef.current !== loadVersion
        || pinnedAppsSaveVersionRef.current !== pinnedStateVersion
      ) {
        return;
      }
      applyPersistedPinnedApps(pinnedApps.pinned_apps, pinnedStateVersion);
      measureStartupMetric("shell.bootstrap.deferred_payloads", deferredStartedAt, {
        pinned_app_count: pinnedApps.pinned_apps.length,
        resource: "pinned_apps",
      });
    } catch (loadError) {
      if (signal?.aborted || shellLoadVersionRef.current !== loadVersion) {
        return;
      }
      measureStartupMetric("shell.bootstrap.deferred_error", deferredStartedAt, {
        message: loadError instanceof Error ? loadError.message : "unknown",
        resource: "pinned_apps",
      });
    }
  }

  useEffect(() => {
    void loadShellState();
    return () => cancelShellLoading({ resetRecovery: true });
  }, []);

  useEffect(() => {
    applyShellThemeToDocument(shellTheme);
  }, [shellTheme]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return undefined;
    }
    const mediaQuery = window.matchMedia("(prefers-color-scheme: light)");
    const updateSystemColorScheme = () => setSystemColorScheme(mediaQuery.matches ? "light" : "dark");
    updateSystemColorScheme();
    mediaQuery.addEventListener("change", updateSystemColorScheme);
    return () => mediaQuery.removeEventListener("change", updateSystemColorScheme);
  }, []);

  useEffect(() => {
    pinnedAppIdsRef.current = pinnedAppIds;
  }, [pinnedAppIds]);

  useEffect(() => {
    return () => {
      if (sidebarCloseTimerRef.current !== null) {
        window.clearTimeout(sidebarCloseTimerRef.current);
      }
      if (mobileChatCloseTimerRef.current !== null) {
        window.clearTimeout(mobileChatCloseTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!isMobileLayout || isSidebarPinned || isSidebarOpen) {
      clearSidebarClosing();
    }
  }, [isMobileLayout, isSidebarOpen, isSidebarPinned]);

  useEffect(() => {
    if (!isMobileLayout) {
      clearMobileChatClosing();
      setIsMobileChatOpen(false);
    }
  }, [isMobileLayout]);

  useEffect(() => {
    if (isChatAppActive) {
      clearMobileChatClosing();
      setIsMobileChatOpen(false);
    }
  }, [isChatAppActive]);

  useEffect(() => {
    function handleAppDataChanged(event: MessageEvent) {
      if (!event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { entity_id?: string; owner_app_id?: string; resource?: string; type?: string };
      if (payload.type !== "maverick.app.data-changed"
          || !payload.owner_app_id
          || !payload.resource
          || !frameScope
          || !isMaverickOwnerMessage(event, payload.owner_app_id, frameScope)) {
        return;
      }
      if (payload.owner_app_id !== "app-store"
          || (payload.resource !== "pinned-apps" && payload.resource !== "state")) {
        return;
      }
      listPinnedApps()
        .then((pinnedApps) => applyPersistedPinnedApps(pinnedApps.pinned_apps))
        .catch(() => applyPersistedPinnedApps(["chat"]));
    }

    window.addEventListener("message", handleAppDataChanged);
    return () => window.removeEventListener("message", handleAppDataChanged);
  }, [frameScope]);

  useEffect(() => {
    function handleShellCommand(event: MessageEvent) {
      if (
        (!isShellWindowMessage(event)
          && (!frameScope || !isRegisteredMaverickFrameMessage(event, frameScope)))
        || !event.data
        || typeof event.data !== "object"
      ) {
        return;
      }
      const payload = event.data as { type?: string };
      if (payload.type === "maverick.shell.logout") {
        handleLogout().catch((logoutError) => {
          setError(logoutError instanceof Error ? logoutError.message : "Unable to logout.");
        });
      }
    }

    window.addEventListener("message", handleShellCommand);
    return () => window.removeEventListener("message", handleShellCommand);
  }, [frameScope]);

  const registryActiveApp = preferredActiveApp(apps, activeAppId);
  const provisionalActiveApp = useMemo(
    () => (isLoading && activeAppId ? provisionalMountedApp(activeAppId) : null),
    [activeAppId, isLoading],
  );
  const activeApp = registryActiveApp ?? provisionalActiveApp;
  const chatApp = apps.find((app) => app.app_id === CHAT_APP_ID) ?? (isLoading ? provisionalMountedApp(CHAT_APP_ID) : null);

  useEffect(() => {
    function handlePopState() {
      const route = currentShellAppRoute();
      setActiveAppId(route.appId);
      setActiveAppParams(route.params);
      if (isSidebarPinned) {
        openSidebar();
      } else {
        closeSidebar();
      }
    }

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [isSidebarPinned]);

  useEffect(() => {
    writeShellSession({
      activeAppId: activeApp?.app_id ?? activeAppId,
      floatingChatMode,
      floatingChatNavigationScope,
      floatingChatThreadId,
      floatingChatWidthPx,
      isSidebarOpen: isSidebarPinned ? true : isSidebarOpen,
      sidebarDetailsWidthPx,
      sidebarMode,
      themeMode,
    });
  }, [
    activeApp?.app_id,
    activeAppId,
    floatingChatMode,
    floatingChatNavigationScope,
    floatingChatThreadId,
    floatingChatWidthPx,
    isSidebarOpen,
    isSidebarPinned,
    sidebarDetailsWidthPx,
    sidebarMode,
    themeMode,
  ]);

  useEffect(() => {
    if (isMobileLayout) {
      return undefined;
    }
    function handleResize() {
      setSidebarDetailsWidthPx((current) => clampSidebarDetailsWidth(current));
      setFloatingChatWidthPx((current) => clampFloatingChatWidth(current));
    }
    handleResize();
    window.addEventListener("resize", handleResize);
    window.visualViewport?.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      window.visualViewport?.removeEventListener("resize", handleResize);
    };
  }, [isMobileLayout]);

  useEffect(() => {
    if (isSidebarPinned) {
      openSidebar();
    }
  }, [isSidebarPinned]);

  useEffect(() => {
    setMobilePrimaryAction({ available: false, label: "", preferredSurface: "app" });
  }, [activeApp?.app_id, activeAppId]);

  useEffect(() => {
    if (activeAppId === null) {
      replaceShellAppRoute(null, {});
      return;
    }
    if (activeApp) {
      replaceShellAppRoute(activeApp.app_id, activeAppParams);
    }
  }, [activeApp?.app_id, activeAppId, JSON.stringify(activeAppParams)]);

  async function openApp(appId: string, params: Record<string, string | boolean | null> = {}) {
    const requestedWorkspaceId = typeof params.workspace_id === "string" && params.workspace_id.trim() ? params.workspace_id.trim() : null;
    const activeWorkspaceId = session?.authenticated ? session.workspace_id : null;
    if (requestedWorkspaceId && requestedWorkspaceId !== activeWorkspaceId) {
      try {
        await switchWorkspace(requestedWorkspaceId);
        cancelShellLoading({ resetRecovery: true });
        await loadShellState();
      } catch (switchError) {
        setError(switchError instanceof Error ? switchError.message : "Unable to switch workspace.");
        return;
      }
    }
    const resolvedParams = resolveAppOpenParams(activeAppId, activeAppParams, appId, params);
    setActiveAppId(appId);
    setActiveAppParams(resolvedParams);
    setIsMobilePinnedAppsOpen(false);
    closeMobileChatPanel();
    if (isSidebarPinned) {
      openSidebar();
    } else {
      closeSidebar();
    }
    pushShellAppRoute(appId, resolvedParams);
  }

  function handleSidebarModeChange(nextMode: SidebarMode) {
    setSidebarMode(nextMode);
    if (nextMode === "fixed" && !isMobileLayout) {
      openSidebar();
    } else {
      clearSidebarClosing();
      setIsSidebarOpen(false);
    }
  }

  function openFloatingChatDock(request: { navigationScope: string | null; placement: "right"; threadId: string | null }) {
    if (request.placement !== "right") {
      return;
    }
    setFloatingChatThreadId(request.threadId);
    setFloatingChatNavigationScope(request.navigationScope);
    setFloatingChatMode("fixed-right");
  }

  function closeFloatingChatDock() {
    setFloatingChatMode("overlay");
  }

  function updateFloatingChatActiveThread(event: { navigationScope: string | null; threadId: string }) {
    const nextThreadId = event.threadId.trim();
    if (!nextThreadId) {
      return;
    }
    const nextNavigationScope = event.navigationScope?.trim() || null;
    setFloatingChatThreadId(nextThreadId);
    if (nextNavigationScope) {
      setFloatingChatNavigationScope(nextNavigationScope);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } finally {
      cancelShellLoading({ resetRecovery: true });
      await shellCacheLifecycle.endSession().catch(() => undefined);
    }
    await loadShellState();
  }

  async function handleInitialProviderConfigured(payload: {
    provider_id: string;
    model_id?: string | null;
    model_reasoning_effort?: string | null;
  }) {
    await configureActiveProvider(payload);
    setSettings(await getProviderSetupSettings());
    setDismissedProviderSetupWorkspaceId(null);
  }

  function openSettingsApp() {
    openApp(SETTINGS_APP_ID);
  }

  function invokeMobilePrimaryAction() {
    if (!mobilePrimaryAction.available) {
      return;
    }
    if (mobilePrimaryAction.preferredSurface === "sidebar") {
      openSidebar();
    }
    setMobilePrimaryActionRequestId((current) => current + 1);
  }

  function openNewChat() {
    openApp(CHAT_APP_ID, newChatRouteParams());
  }

  function pinnedAppsOrDefault(appIds: string[]): string[] {
    return appIds.length ? appIds : ["chat"];
  }

  function applyPersistedPinnedApps(appIds: string[], persistedVersion = pinnedAppsSaveVersionRef.current) {
    const nextAppIds = pinnedAppsOrDefault(appIds);
    rememberPersistedPinnedApps(nextAppIds, persistedVersion);
    pinnedAppIdsRef.current = nextAppIds;
    setPinnedAppIds(nextAppIds);
  }

  function rememberPersistedPinnedApps(appIds: string[], persistedVersion: number) {
    if (persistedVersion < persistedPinnedAppsVersionRef.current) {
      return;
    }
    persistedPinnedAppsVersionRef.current = persistedVersion;
    persistedPinnedAppIdsRef.current = pinnedAppsOrDefault(appIds);
  }

  async function handlePinnedAppsReorder(nextPinnedAppIds: string[]) {
    const saveVersion = pinnedAppsSaveVersionRef.current + 1;
    pinnedAppsSaveVersionRef.current = saveVersion;
    pinnedAppIdsRef.current = nextPinnedAppIds;
    setPinnedAppIds(nextPinnedAppIds);
    try {
      const savedPinnedApps = await savePinnedApps(nextPinnedAppIds);
      rememberPersistedPinnedApps(savedPinnedApps.pinned_apps, saveVersion);
      if (pinnedAppsSaveVersionRef.current !== saveVersion) {
        return;
      }
      const savedAppIds = pinnedAppsOrDefault(savedPinnedApps.pinned_apps);
      pinnedAppIdsRef.current = savedAppIds;
      setPinnedAppIds(savedAppIds);
      notifyAppDataChanged("app-store", "pinned-apps");
    } catch (saveError) {
      if (pinnedAppsSaveVersionRef.current !== saveVersion) {
        return;
      }
      const rollbackAppIds = pinnedAppsOrDefault(persistedPinnedAppIdsRef.current);
      pinnedAppIdsRef.current = rollbackAppIds;
      setPinnedAppIds(rollbackAppIds);
      setError(saveError instanceof Error ? saveError.message : "Unable to save app rail order.");
    }
  }

  if (isLoading && session === null) {
    return (
      <main className="bs-shell">
        <div className="bs-shell-initial-pending">
          <ShellPendingIndicator ariaLabel="Loading workspace" label="Loading workspace" />
        </div>
      </main>
    );
  }

  if (!session?.authenticated || !frameScope) {
    return <LoginScreen onAuthenticated={(authenticatedSession) => {
      setSession(authenticatedSession);
      shellRetryCoordinator.setScope(JSON.stringify([
        authenticatedSession.user.user_id,
        authenticatedSession.workspace_id,
        "base-shell",
      ]));
      void loadShellState();
    }} />;
  }

  const activeWorkspaceId = session.workspace_id;
  const needsProviderSetup =
    !!settings && !settings.provider.active_provider && dismissedProviderSetupWorkspaceId !== activeWorkspaceId;

  return (
    <main
      className={`bs-shell is-sidebar-mode-${sidebarMode} ${isSidebarOpen ? "is-sidebar-open" : ""} ${isSidebarClosing ? "is-sidebar-closing" : ""} ${isSidebarResizing ? "is-sidebar-resizing" : ""} ${isFloatingChatFixed ? "is-floating-chat-fixed" : ""} ${isFloatingChatResizing ? "is-floating-chat-resizing" : ""} ${isMobileLayout ? "is-mobile-layout" : ""}`}
      style={shellStyle}
    >
      {isMobileLayout ? (
        <MobileShellHeader
          activeApp={activeApp}
          chatApp={chatApp}
          isPinnedAppsOpen={isMobilePinnedAppsOpen}
          isMobileChatOpen={isMobileChatOpen || isMobileChatClosing}
          isPrimaryActionAvailable={mobilePrimaryAction.available}
          isSidebarOpen={isSidebarOpen || isSidebarClosing}
          showMobileChatAction={!isChatAppActive}
          onCloseMobileChat={closeMobileChatPanel}
          onOpenMobileChat={openMobileChatPanel}
          onOpenNewChat={openNewChat}
          onTogglePinnedApps={toggleMobilePinnedApps}
          onToggleSidebar={toggleMobileSidebar}
          onPrimaryAction={invokeMobilePrimaryAction}
          primaryActionLabel={mobilePrimaryAction.label}
          shellTheme={shellTheme}
        />
      ) : null}
      {isMobileLayout ? (
        <MobilePinnedAppsPanel
          activeAppId={activeApp?.app_id ?? activeAppId}
          apps={railApps}
          isOpen={isMobilePinnedAppsOpen}
          isLoading={isLoading && railApps.length === 0}
          onOpenApp={openApp}
          onOpenSettings={openSettingsApp}
          settingsApp={settingsShortcutApp}
        />
      ) : null}
      <div className="bs-workspace-view-shell">
        <WorkspaceView
          activeApp={activeApp}
          activeAppParams={activeAppParams}
          activeWorkspaceId={activeWorkspaceId}
          apps={apps}
          cacheUserId={session.user.user_id}
          error={error}
          isLoading={isLoading}
          isMobileLayout={isMobileLayout}
          frameScope={frameScope}
          onOpenApp={openApp}
          sessionExpiresAt={session.expires_at}
          shellTheme={shellTheme}
        />
      </div>
      <Sidebar
        activeAppId={activeApp?.app_id ?? activeAppId}
        activeAppParams={activeAppParams}
        activeWorkspaceId={activeWorkspaceId}
        apps={apps}
        frameScope={frameScope}
        isLoading={isLoading}
        isWorkspacesLoading={isWorkspacesLoading}
        isOpen={isSidebarOpen}
        isMobileLayout={isMobileLayout}
        isPinned={isSidebarPinned}
        mode={sidebarMode}
        mobilePrimaryActionRequestId={mobilePrimaryActionRequestId}
        onClose={closeSidebar}
        onModeChange={handleSidebarModeChange}
        onOpenApp={openApp}
        onOpenSidebar={openSidebar}
        onPrimaryActionStateChange={setMobilePrimaryAction}
        onOpenSettings={openSettingsApp}
        onReorderPinnedApps={handlePinnedAppsReorder}
        onWorkspaceChanged={loadShellState}
        pinnedAppIds={pinnedAppIds}
        railMetrics={shellSidebarMetrics}
        sidebarDetailsWidthPx={sidebarDetailsWidthPx}
        shellTheme={shellTheme}
        themeMode={themeMode}
        onThemeModeChange={setThemeMode}
        onSidebarDetailsWidthChange={setSidebarDetailsWidthPx}
        onSidebarResizeActiveChange={setIsSidebarResizing}
        user={session.user}
        workspaces={workspaces}
      />
      <FloatingChatHost
        activeApp={activeApp}
        activeAppParams={activeAppParams}
        activeWorkspaceId={activeWorkspaceId}
        frameScope={frameScope}
        floatingChatMode={floatingChatMode}
        isChatAppActive={isChatAppActive}
        isMobileChatClosing={isMobileChatClosing}
        isMobileChatOpen={isMobileChatOpen}
        isMobileLayout={isMobileLayout}
        navigationScope={floatingChatNavigationScope}
        onActiveThreadChange={updateFloatingChatActiveThread}
        onCloseDock={closeFloatingChatDock}
        onCloseMobileChat={closeMobileChatPanel}
        onOpenApp={openApp}
        onOpenDock={openFloatingChatDock}
        onResizeActiveChange={setIsFloatingChatResizing}
        onWidthChange={setFloatingChatWidthPx}
        shellTheme={shellTheme}
        threadId={floatingChatThreadId}
        user={session.user}
        widthPx={floatingChatWidthPx}
      />
      <ProviderSetupDialog
        onClose={() => setDismissedProviderSetupWorkspaceId(activeWorkspaceId)}
        onConfigure={handleInitialProviderConfigured}
        open={needsProviderSetup}
        settings={settings}
      />
    </main>
  );
}

function provisionalMountedApp(appId: string): AppRegistryItem {
  return {
    app_id: appId,
    name: appId,
    version: "",
    description: "",
    publisher: "",
    status: "enabled",
    distribution_mode: "",
    source_access: "",
    views: [],
    provides: [],
    requires: [],
    logo: null,
    frontend_mount: `/apps/${encodeURIComponent(appId)}/`,
    frontend_role: "workspace",
    frontend_launchable: true,
    backend_mount: "",
  };
}
