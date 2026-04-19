import { AppRegistryItem, PlatformStatus, ProviderStatus, RuntimeStatus } from "../api";
import { Badge } from "../ui";
import { AppLogo } from "./AppLogo";

export function TopBar({
  activeApp,
  isSidebarOpen,
  onToggleSidebar,
  provider,
  runtime,
  status,
}: {
  activeApp: AppRegistryItem | null;
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  provider: ProviderStatus | null;
  runtime: RuntimeStatus | null;
  status: PlatformStatus | null;
}) {
  const runningSessions = runtime?.sessions.filter((session) => session.status === "running").length ?? 0;
  return (
    <section className="bs-app-topbar">
      <div className="bs-app-topbar__group">
        <button aria-label={isSidebarOpen ? "Chiudi menu" : "Apri menu"} className="bs-icon-button" onClick={onToggleSidebar} type="button">
          <span aria-hidden="true">{isSidebarOpen ? "×" : "☰"}</span>
        </button>
        <div className="bs-app-topbar__copy">
          {activeApp ? <AppLogo app={activeApp} className="bs-app-logo--topbar" /> : null}
          <span className="bs-app-topbar__subtitle">{activeApp?.description || "Console app montate dal core"}</span>
          <strong className="bs-app-topbar__title">{activeApp?.name || "Installed Apps"}</strong>
        </div>
      </div>
      <div className="bs-app-topbar__actions">
        <Badge tone="success">{provider?.active_provider.label || "Provider"}</Badge>
        <Badge>{runningSessions} runtime</Badge>
        <Badge tone="primary">{status?.workspace_id || "default"}</Badge>
        <Badge>{status?.status || "loading"}</Badge>
      </div>
    </section>
  );
}
