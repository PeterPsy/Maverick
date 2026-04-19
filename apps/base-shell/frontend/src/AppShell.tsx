import { useEffect, useMemo, useState } from "react";
import { AppRegistryItem, getPlatformStatus, listApps, PlatformStatus } from "./api";
import { nextPinnedAppIds, preferredActiveApp } from "./navigation";
import { readShellSession, writeShellSession } from "./session";
import { useMobileLayout } from "./hooks/useMobileLayout";
import { Sidebar } from "./components/Sidebar";
import { ShellDialog, ShellDialogs } from "./components/ShellDialogs";
import { TopBar } from "./components/TopBar";
import { WorkspaceView } from "./components/WorkspaceView";

export function AppShell() {
  const initialSession = useMemo(() => readShellSession(), []);
  const [apps, setApps] = useState<AppRegistryItem[]>([]);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [activeAppId, setActiveAppId] = useState<string | null>(initialSession.activeAppId);
  const [isSidebarOpen, setIsSidebarOpen] = useState(initialSession.isSidebarOpen);
  const [pinnedAppIds, setPinnedAppIds] = useState(initialSession.pinnedAppIds);
  const [activeDialog, setActiveDialog] = useState<ShellDialog>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMobileLayout = useMobileLayout();

  useEffect(() => {
    let cancelled = false;
    async function loadShellState() {
      try {
        const [registry, platformStatus] = await Promise.all([listApps(), getPlatformStatus()]);
        if (cancelled) {
          return;
        }
        setApps(registry.items);
        setStatus(platformStatus);
        setError(null);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Errore sconosciuto.");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }
    loadShellState();
    return () => {
      cancelled = true;
    };
  }, []);

  const activeApp = preferredActiveApp(apps, activeAppId);

  useEffect(() => {
    writeShellSession({
      activeAppId,
      isSidebarOpen,
      pinnedAppIds,
    });
  }, [activeAppId, isSidebarOpen, pinnedAppIds]);

  function openApp(appId: string) {
    setActiveAppId(appId);
    setIsSidebarOpen(false);
  }

  function openApps() {
    setActiveAppId(null);
    setIsSidebarOpen(false);
  }

  function togglePinnedApp(appId: string) {
    setPinnedAppIds((current) => nextPinnedAppIds(current, appId));
  }

  return (
    <main className={`bs-shell ${isSidebarOpen ? "is-sidebar-open" : ""} ${isMobileLayout ? "is-mobile-layout" : ""}`}>
      <div className="bs-workspace-view-shell">
        <TopBar activeApp={activeApp} isSidebarOpen={isSidebarOpen} onToggleSidebar={() => setIsSidebarOpen((open) => !open)} status={status} />
        <WorkspaceView
          activeApp={activeApp}
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
        apps={apps}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpenApp={openApp}
        onOpenApps={openApps}
        onOpenSettings={() => setActiveDialog("settings")}
        onOpenTutorial={() => setActiveDialog("tutorial")}
        pinnedAppIds={pinnedAppIds}
      />
      <button aria-label="Apri menu" className="bs-panel-peek bs-panel-peek--left" onClick={() => setIsSidebarOpen(true)} type="button">
        <span aria-hidden="true">›</span>
      </button>
      <ShellDialogs activeDialog={activeDialog} onClose={() => setActiveDialog(null)} />
    </main>
  );
}
