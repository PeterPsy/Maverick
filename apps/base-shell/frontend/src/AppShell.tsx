import { useEffect, useMemo, useRef, useState } from "react";
import {
  AppRegistryItem,
  clearRuntimeSessions,
  configureActiveProvider,
  getPlatformSettings,
  getPlatformStatus,
  getSession,
  listApps,
  listPinnedApps,
  listWorkspaces,
  logout,
  PlatformSettings,
  PlatformStatus,
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
  shellAppRailApps,
} from "./navigation";
import { readShellSession, resolveInitialSidebarOpen, writeShellSession } from "./session";
import type { SidebarMode } from "./session";
import { getInitialMobileLayout, useMobileLayout } from "./hooks/useMobileLayout";
import { useSidebarRailMetrics } from "./hooks/useSidebarRailMetrics";
import { LoginScreen } from "./components/LoginScreen";
import { MobileShellHeader } from "./components/MobileShellHeader";
import { Sidebar } from "./components/Sidebar";
import { ShellOverlayWidgets } from "./components/ShellOverlayWidgets";
import { ShellDialog, ShellDialogs } from "./components/ShellDialogs";
import { ProviderSetupDialog } from "./components/ProviderSetupDialog";
import { WorkspaceView } from "./components/WorkspaceView";
import type { WidgetPrimaryActionState } from "./components/WidgetSlot";

const MOBILE_SIDEBAR_TRANSITION_MS = 220;

export function AppShell() {
  const initialSession = useMemo(() => readShellSession(), []);
  const initialRoute = useMemo(() => currentShellAppRoute(), []);
  const isInitialChatLaunch = useMemo(() => isInitialChatLaunchRoute(initialRoute), [initialRoute]);
  const initialLaunchRoute = useMemo(() => initialShellLaunchRoute(initialRoute), [initialRoute]);
  const initialIsMobileLayout = useMemo(() => getInitialMobileLayout(), []);
  const initialActiveAppId = initialLaunchRoute.appId || initialSession.activeAppId;
  const [apps, setApps] = useState<AppRegistryItem[]>([]);
  const [pinnedAppIds, setPinnedAppIds] = useState<string[]>(["chat"]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [activeAppId, setActiveAppId] = useState<string | null>(initialActiveAppId);
  const [activeAppParams, setActiveAppParams] = useState<Record<string, string | boolean | null>>(initialLaunchRoute.params);
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>(isInitialChatLaunch ? "rail" : initialSession.sidebarMode);
  const [isSidebarOpen, setIsSidebarOpen] = useState(() =>
    resolveInitialSidebarOpen(initialSession, {
      isInitialChatLaunch,
      isMobileLayout: initialIsMobileLayout,
    }),
  );
  const [isSidebarClosing, setIsSidebarClosing] = useState(false);
  const [activeDialog, setActiveDialog] = useState<ShellDialog>(null);
  const [dismissedProviderSetupWorkspaceId, setDismissedProviderSetupWorkspaceId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mobilePrimaryAction, setMobilePrimaryAction] = useState<WidgetPrimaryActionState>({
    available: false,
    label: "",
    preferredSurface: "app",
  });
  const [mobilePrimaryActionRequestId, setMobilePrimaryActionRequestId] = useState(0);
  const isMobileLayout = useMobileLayout();
  const isSidebarPinned = sidebarMode === "fixed" && !isMobileLayout;
  const sidebarCloseTimerRef = useRef<number | null>(null);
  const pinnedAppIdsRef = useRef(pinnedAppIds);
  const pinnedAppsSaveVersionRef = useRef(0);
  const persistedPinnedAppIdsRef = useRef(pinnedAppIds);
  const persistedPinnedAppsVersionRef = useRef(0);
  const railApps = shellAppRailApps(apps, pinnedAppIds);
  const shellRailItemCount = isLoading && railApps.length === 0 ? 4 : railApps.length + 1;
  const shellSidebarMetrics = useSidebarRailMetrics(shellRailItemCount, isMobileLayout);

  function clearSidebarClosing() {
    if (sidebarCloseTimerRef.current !== null) {
      window.clearTimeout(sidebarCloseTimerRef.current);
      sidebarCloseTimerRef.current = null;
    }
    setIsSidebarClosing(false);
  }

  function openSidebar() {
    clearSidebarClosing();
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

  async function loadShellState() {
    setIsLoading(true);
    try {
      const currentSession = await getSession();
      setSession(currentSession);
      if (!currentSession.authenticated) {
        setApps([]);
        setStatus(null);
        setWorkspaces([]);
        setSettings(null);
        setError(null);
        return;
      }
      const [registry, platformStatus, workspacePayload, platformSettings, pinnedApps] = await Promise.all([
        listApps(),
        getPlatformStatus(),
        listWorkspaces(),
        getPlatformSettings(),
        listPinnedApps().catch(() => ({ pinned_apps: ["chat"] })),
      ]);
      setApps(registry.items);
      applyPersistedPinnedApps(pinnedApps.pinned_apps);
      setStatus(platformStatus);
      setWorkspaces(workspacePayload.items);
      setSettings(platformSettings);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Errore sconosciuto.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadShellState();
  }, []);

  useEffect(() => {
    pinnedAppIdsRef.current = pinnedAppIds;
  }, [pinnedAppIds]);

  useEffect(() => {
    return () => {
      if (sidebarCloseTimerRef.current !== null) {
        window.clearTimeout(sidebarCloseTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!isMobileLayout || isSidebarPinned || isSidebarOpen) {
      clearSidebarClosing();
    }
  }, [isMobileLayout, isSidebarOpen, isSidebarPinned]);

  useEffect(() => {
    function handleAppDataChanged(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.type !== "maverick.app.data-changed" || payload.owner_app_id !== "app-store") {
        return;
      }
      if (payload.resource && payload.resource !== "pinned-apps" && payload.resource !== "state") {
        return;
      }
      listPinnedApps()
        .then((pinnedApps) => applyPersistedPinnedApps(pinnedApps.pinned_apps))
        .catch(() => applyPersistedPinnedApps(["chat"]));
    }

    window.addEventListener("message", handleAppDataChanged);
    return () => window.removeEventListener("message", handleAppDataChanged);
  }, []);

  const registryActiveApp = preferredActiveApp(apps, activeAppId);
  const provisionalActiveApp = useMemo(
    () => (isLoading && activeAppId ? provisionalMountedApp(activeAppId) : null),
    [activeAppId, isLoading],
  );
  const activeApp = registryActiveApp ?? provisionalActiveApp;

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
      isSidebarOpen: isSidebarPinned ? true : isSidebarOpen,
      sidebarMode,
    });
  }, [activeApp?.app_id, activeAppId, isSidebarOpen, isSidebarPinned, sidebarMode]);

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
    const activeWorkspaceId = status?.workspace_id || (session?.authenticated ? session.workspace_id : null);
    if (requestedWorkspaceId && requestedWorkspaceId !== activeWorkspaceId) {
      try {
        await switchWorkspace(requestedWorkspaceId);
        await loadShellState();
      } catch (switchError) {
        setError(switchError instanceof Error ? switchError.message : "Unable to switch workspace.");
        return;
      }
    }
    setActiveAppId(appId);
    setActiveAppParams(params);
    if (isSidebarPinned) {
      openSidebar();
    } else {
      closeSidebar();
    }
    pushShellAppRoute(appId, params);
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

  async function handleLogout() {
    await logout();
    setActiveDialog(null);
    await loadShellState();
  }

  async function handleProviderModelSettingsChanged(modelId: string, reasoningEffort: string | null) {
    const providerId = settings?.provider.active_provider?.provider_id;
    if (!providerId) {
      throw new Error("Provider non caricato.");
    }
    await configureActiveProvider({
      provider_id: providerId,
      model_id: modelId,
      model_reasoning_effort: reasoningEffort,
    });
    setSettings(await getPlatformSettings());
  }

  async function handleInitialProviderConfigured(payload: {
    provider_id: string;
    model_id?: string | null;
    model_reasoning_effort?: string | null;
  }) {
    await configureActiveProvider(payload);
    setSettings(await getPlatformSettings());
    setDismissedProviderSetupWorkspaceId(null);
  }

  async function handleClearRuntimeSessions(sessionIds?: string[]) {
    const payload = await clearRuntimeSessions(sessionIds);
    if (payload.deleted_threads > 0) {
      notifyAppDataChanged("chat", "threads");
      for (const threadId of payload.deleted_thread_ids) {
        notifyAppDataChanged("chat", "threads", { deleted_thread_id: threadId });
      }
    }
    setSettings(await getPlatformSettings());
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
    return <main className="bs-shell" />;
  }

  if (!session?.authenticated) {
    return <LoginScreen onAuthenticated={(authenticatedSession) => {
      setSession(authenticatedSession);
      loadShellState();
    }} />;
  }

  const activeWorkspaceId = status?.workspace_id || session.workspace_id;
  const needsProviderSetup =
    !!settings && !settings.provider.active_provider && dismissedProviderSetupWorkspaceId !== activeWorkspaceId;

  return (
    <main
      className={`bs-shell is-sidebar-mode-${sidebarMode} ${isSidebarOpen ? "is-sidebar-open" : ""} ${isSidebarClosing ? "is-sidebar-closing" : ""} ${isMobileLayout ? "is-mobile-layout" : ""}`}
      style={shellSidebarMetrics}
    >
      {isMobileLayout ? (
        <MobileShellHeader
          activeApp={activeApp}
          isPrimaryActionAvailable={mobilePrimaryAction.available}
          isSidebarOpen={isSidebarOpen || isSidebarClosing}
          onOpenNewChat={openNewChat}
          onOpenSidebar={openSidebar}
          onPrimaryAction={invokeMobilePrimaryAction}
          primaryActionLabel={mobilePrimaryAction.label}
        />
      ) : null}
      <div className="bs-workspace-view-shell">
        <WorkspaceView
          activeApp={activeApp}
          activeAppParams={activeAppParams}
          activeWorkspaceId={activeWorkspaceId}
          apps={apps}
          error={error}
          isLoading={isLoading}
          isMobileLayout={isMobileLayout}
          onOpenApp={openApp}
        />
      </div>
      <Sidebar
        activeAppId={activeApp?.app_id ?? activeAppId}
        activeAppParams={activeAppParams}
        activeWorkspaceId={activeWorkspaceId}
        apps={apps}
        isLoading={isLoading}
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
        onOpenSettings={() => setActiveDialog("settings")}
        onReorderPinnedApps={handlePinnedAppsReorder}
        onWorkspaceChanged={loadShellState}
        pinnedAppIds={pinnedAppIds}
        railMetrics={shellSidebarMetrics}
        user={session.user}
        workspaces={workspaces}
      />
      <ShellOverlayWidgets activeApp={activeApp} activeWorkspaceId={activeWorkspaceId} onOpenApp={openApp} user={session.user} />
      <ShellDialogs
        activeDialog={activeDialog}
        onClose={() => setActiveDialog(null)}
        onLogout={handleLogout}
        onClearRuntimeSessions={handleClearRuntimeSessions}
        onProviderModelSettingsChanged={handleProviderModelSettingsChanged}
        settings={settings}
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
    backend_mount: "",
  };
}
