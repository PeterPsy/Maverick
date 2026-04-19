import { useEffect, useMemo, useState } from "react";
import {
  AppRegistryItem,
  getPlatformSettings,
  getPlatformStatus,
  getSession,
  listApps,
  listWorkspaces,
  logout,
  PlatformSettings,
  PlatformStatus,
  SessionPayload,
  WorkspaceItem,
} from "./api";
import { nextPinnedAppIds, preferredActiveApp } from "./navigation";
import { readShellSession, writeShellSession } from "./session";
import { useMobileLayout } from "./hooks/useMobileLayout";
import { LoginScreen } from "./components/LoginScreen";
import { Sidebar } from "./components/Sidebar";
import { ShellDialog, ShellDialogs } from "./components/ShellDialogs";
import { WorkspaceView } from "./components/WorkspaceView";

export function AppShell() {
  const initialSession = useMemo(() => readShellSession(), []);
  const [apps, setApps] = useState<AppRegistryItem[]>([]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [activeAppId, setActiveAppId] = useState<string | null>(initialSession.activeAppId);
  const [activeAppParams, setActiveAppParams] = useState<Record<string, string | boolean | null>>({});
  const [isSidebarOpen, setIsSidebarOpen] = useState(initialSession.isSidebarOpen);
  const [pinnedAppIds, setPinnedAppIds] = useState(initialSession.pinnedAppIds);
  const [activeDialog, setActiveDialog] = useState<ShellDialog>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMobileLayout = useMobileLayout();

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
    writeShellSession({
      activeAppId,
      isSidebarOpen,
      pinnedAppIds,
    });
  }, [activeAppId, isSidebarOpen, pinnedAppIds]);

  function openApp(appId: string, params: Record<string, string | boolean | null> = {}) {
    setActiveAppId(appId);
    setActiveAppParams(params);
    setIsSidebarOpen(false);
  }

  function openApps() {
    setActiveAppId(null);
    setActiveAppParams({});
    setIsSidebarOpen(false);
  }

  function togglePinnedApp(appId: string) {
    setPinnedAppIds((current) => nextPinnedAppIds(current, appId));
  }

  async function handleLogout() {
    await logout();
    setActiveDialog(null);
    await loadShellState();
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

  return (
    <main className={`bs-shell ${isSidebarOpen ? "is-sidebar-open" : ""} ${isMobileLayout ? "is-mobile-layout" : ""}`}>
      <div className="bs-workspace-view-shell">
        <WorkspaceView
          activeApp={activeApp}
          activeAppParams={activeAppParams}
          apps={apps}
          error={error}
          isLoading={isLoading}
          onOpenApp={openApp}
          onTogglePinnedApp={togglePinnedApp}
          pinnedAppIds={pinnedAppIds}
        />
      </div>
      <button aria-label="Chiudi menu" className="bs-shell__backdrop" onClick={() => setIsSidebarOpen(false)} type="button" />
      <Sidebar
        activeAppId={activeApp?.app_id ?? activeAppId}
        activeWorkspaceId={status?.workspace_id || session.workspace_id}
        apps={apps}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpenApp={openApp}
        onOpenApps={openApps}
        onOpenSettings={() => setActiveDialog("settings")}
        onOpenTutorial={() => setActiveDialog("tutorial")}
        onWorkspaceChanged={loadShellState}
        pinnedAppIds={pinnedAppIds}
        user={session.user}
        workspaces={workspaces}
      />
      <button aria-label="Apri menu" className="bs-panel-peek bs-panel-peek--left" onClick={() => setIsSidebarOpen(true)} type="button">
        <span aria-hidden="true">›</span>
      </button>
      <ShellDialogs activeDialog={activeDialog} onClose={() => setActiveDialog(null)} onLogout={handleLogout} settings={settings} />
    </main>
  );
}
