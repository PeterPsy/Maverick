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
  SessionPayload,
  switchWorkspace,
  WorkspaceItem,
} from "./api";
import { currentShellAppRoute, preferredActiveApp, pushShellAppRoute, replaceShellAppRoute, shellVisibleApps } from "./navigation";
import { readShellSession, writeShellSession } from "./session";
import type { SidebarMode } from "./session";
import { useMobileLayout } from "./hooks/useMobileLayout";
import { LoginScreen } from "./components/LoginScreen";
import { Sidebar, sidebarRailMetrics } from "./components/Sidebar";
import { ShellOverlayWidgets } from "./components/ShellOverlayWidgets";
import { ShellDialog, ShellDialogs } from "./components/ShellDialogs";
import { ProviderSetupDialog } from "./components/ProviderSetupDialog";
import { WorkspaceView } from "./components/WorkspaceView";

const MOBILE_SIDEBAR_TRANSITION_MS = 220;

export function AppShell() {
  const initialSession = useMemo(() => readShellSession(), []);
  const initialRoute = useMemo(() => currentShellAppRoute(), []);
  const initialActiveAppId = useMemo(() => initialRoute.appId || initialSession.activeAppId, [initialRoute.appId, initialSession.activeAppId]);
  const [apps, setApps] = useState<AppRegistryItem[]>([]);
  const [pinnedAppIds, setPinnedAppIds] = useState<string[]>(["chat"]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [activeAppId, setActiveAppId] = useState<string | null>(initialActiveAppId);
  const [activeAppParams, setActiveAppParams] = useState<Record<string, string | boolean | null>>(initialRoute.params);
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>(initialSession.sidebarMode);
  const [isSidebarOpen, setIsSidebarOpen] = useState(initialSession.sidebarMode === "fixed" ? true : initialSession.isSidebarOpen);
  const [isSidebarClosing, setIsSidebarClosing] = useState(false);
  const [activeDialog, setActiveDialog] = useState<ShellDialog>(null);
  const [dismissedProviderSetupWorkspaceId, setDismissedProviderSetupWorkspaceId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMobileLayout = useMobileLayout();
  const isSidebarPinned = sidebarMode === "fixed" && !isMobileLayout;
  const sidebarCloseTimerRef = useRef<number | null>(null);

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
      setPinnedAppIds(pinnedApps.pinned_apps.length ? pinnedApps.pinned_apps : ["chat"]);
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
        .then((pinnedApps) => setPinnedAppIds(pinnedApps.pinned_apps.length ? pinnedApps.pinned_apps : ["chat"]))
        .catch(() => setPinnedAppIds(["chat"]));
    }

    window.addEventListener("message", handleAppDataChanged);
    return () => window.removeEventListener("message", handleAppDataChanged);
  }, []);

  const activeApp = preferredActiveApp(apps, activeAppId);

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
  const visiblePinnedAppIds = new Set(pinnedAppIds);
  const shellSidebarMetrics = sidebarRailMetrics(shellVisibleApps(apps).filter((app) => visiblePinnedAppIds.has(app.app_id)).length + 1);

  return (
    <main
      className={`bs-shell is-sidebar-mode-${sidebarMode} ${isSidebarOpen ? "is-sidebar-open" : ""} ${isSidebarClosing ? "is-sidebar-closing" : ""} ${isMobileLayout ? "is-mobile-layout" : ""}`}
      style={shellSidebarMetrics}
    >
      <div className="bs-workspace-view-shell">
        <WorkspaceView
          activeApp={activeApp}
          activeAppParams={activeAppParams}
          activeWorkspaceId={activeWorkspaceId}
          apps={apps}
          error={error}
          isLoading={isLoading}
          onOpenApp={openApp}
          onOpenSidebar={openSidebar}
        />
      </div>
      <Sidebar
        activeAppId={activeApp?.app_id ?? activeAppId}
        activeWorkspaceId={activeWorkspaceId}
        apps={apps}
        isLoading={isLoading}
        isOpen={isSidebarOpen}
        isMobileLayout={isMobileLayout}
        isPinned={isSidebarPinned}
        mode={sidebarMode}
        onClose={closeSidebar}
        onModeChange={handleSidebarModeChange}
        onOpenApp={openApp}
        onOpenSidebar={openSidebar}
        onOpenSettings={() => setActiveDialog("settings")}
        onWorkspaceChanged={loadShellState}
        pinnedAppIds={pinnedAppIds}
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
