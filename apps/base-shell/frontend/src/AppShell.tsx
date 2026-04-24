import { useEffect, useMemo, useState } from "react";
import {
  AppRegistryItem,
  clearRuntimeSessions,
  configureActiveProvider,
  getPlatformSettings,
  getPlatformStatus,
  getSession,
  listApps,
  listWorkspaces,
  logout,
  PlatformSettings,
  PlatformStatus,
  SessionPayload,
  switchWorkspace,
  WorkspaceItem,
} from "./api";
import { currentShellAppRoute, preferredActiveApp, pushShellAppRoute, replaceShellAppRoute } from "./navigation";
import { readShellSession, writeShellSession } from "./session";
import { useMobileLayout } from "./hooks/useMobileLayout";
import { LoginScreen } from "./components/LoginScreen";
import { Sidebar } from "./components/Sidebar";
import { ShellOverlayWidgets } from "./components/ShellOverlayWidgets";
import { ShellDialog, ShellDialogs } from "./components/ShellDialogs";
import { WorkspaceView } from "./components/WorkspaceView";

export function AppShell() {
  const initialSession = useMemo(() => readShellSession(), []);
  const initialRoute = useMemo(() => currentShellAppRoute(), []);
  const [apps, setApps] = useState<AppRegistryItem[]>([]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [activeAppId, setActiveAppId] = useState<string | null>(initialRoute.appId || initialSession.activeAppId);
  const [activeAppParams, setActiveAppParams] = useState<Record<string, string | boolean | null>>(initialRoute.params);
  const [isSidebarOpen, setIsSidebarOpen] = useState(initialSession.isSidebarOpen);
  const [activeDialog, setActiveDialog] = useState<ShellDialog>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMobileLayout = useMobileLayout();

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
      const [registry, platformStatus, workspacePayload, platformSettings] = await Promise.all([
        listApps(),
        getPlatformStatus(),
        listWorkspaces(),
        getPlatformSettings(),
      ]);
      setApps(registry.items);
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

  const activeApp = preferredActiveApp(apps, activeAppId);

  useEffect(() => {
    function handlePopState() {
      const route = currentShellAppRoute();
      setActiveAppId(route.appId);
      setActiveAppParams(route.params);
      setIsSidebarOpen(false);
    }

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    writeShellSession({
      activeAppId: activeApp?.app_id ?? activeAppId,
      isSidebarOpen,
    });
  }, [activeApp?.app_id, activeAppId, isSidebarOpen]);

  useEffect(() => {
    if (activeApp) {
      replaceShellAppRoute(activeApp.app_id, activeAppParams);
    }
  }, [activeApp?.app_id, JSON.stringify(activeAppParams)]);

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
    setIsSidebarOpen(false);
    pushShellAppRoute(appId, params);
  }

  function openApps() {
    const appStore = apps.find((app) => app.app_id === "app-store" && app.frontend_mount);
    setActiveAppId(appStore ? appStore.app_id : null);
    setActiveAppParams({});
    setIsSidebarOpen(false);
    pushShellAppRoute(appStore ? appStore.app_id : null, {});
  }

  async function handleLogout() {
    await logout();
    setActiveDialog(null);
    await loadShellState();
  }

  async function handleProviderModelSettingsChanged(modelId: string, reasoningEffort: string | null) {
    const providerId = settings?.provider.active_provider.provider_id;
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

  return (
    <main className={`bs-shell ${isSidebarOpen ? "is-sidebar-open" : ""} ${isMobileLayout ? "is-mobile-layout" : ""}`}>
      <div className="bs-workspace-view-shell">
        <WorkspaceView
          activeApp={activeApp}
          activeAppParams={activeAppParams}
          activeWorkspaceId={activeWorkspaceId}
          apps={apps}
          error={error}
          isLoading={isLoading}
          onOpenApp={openApp}
        />
      </div>
      <button aria-label="Chiudi menu" className="bs-shell__backdrop" onClick={() => setIsSidebarOpen(false)} type="button" />
      <Sidebar
        activeAppId={activeApp?.app_id ?? activeAppId}
        activeWorkspaceId={activeWorkspaceId}
        apps={apps}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpenApp={openApp}
        onOpenApps={openApps}
        onOpenSettings={() => setActiveDialog("settings")}
        onOpenTutorial={() => setActiveDialog("tutorial")}
        onWorkspaceChanged={loadShellState}
        user={session.user}
        workspaces={workspaces}
      />
      <button aria-label="Apri menu" className="bs-panel-peek bs-panel-peek--left" onClick={() => setIsSidebarOpen(true)} type="button">
        <span aria-hidden="true" className="material-symbols-rounded">menu</span>
      </button>
      <ShellOverlayWidgets activeApp={activeApp} activeWorkspaceId={activeWorkspaceId} onOpenApp={openApp} user={session.user} />
      <ShellDialogs
        activeDialog={activeDialog}
        onClose={() => setActiveDialog(null)}
        onLogout={handleLogout}
        onClearRuntimeSessions={handleClearRuntimeSessions}
        onProviderModelSettingsChanged={handleProviderModelSettingsChanged}
        settings={settings}
      />
    </main>
  );
}
