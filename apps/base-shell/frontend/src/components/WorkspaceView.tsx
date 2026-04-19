import { AppRegistryItem } from "../api";
import { AppsPanel } from "./AppsPanel";

export function WorkspaceView({
  activeApp,
  apps,
  error,
  isLoading,
  onOpenApp,
  onTogglePinnedApp,
  pinnedAppIds,
}: {
  activeApp: AppRegistryItem | null;
  apps: AppRegistryItem[];
  error: string | null;
  isLoading: boolean;
  onOpenApp: (appId: string) => void;
  onTogglePinnedApp: (appId: string) => void;
  pinnedAppIds: string[];
}) {
  if (!activeApp) {
    return (
      <AppsPanel
        apps={apps}
        error={error}
        isLoading={isLoading}
        onOpenApp={onOpenApp}
        onTogglePinnedApp={onTogglePinnedApp}
        pinnedAppIds={pinnedAppIds}
      />
    );
  }
  return (
    <section className="bs-workspace-app-panel" aria-label={`${activeApp.name} app`}>
      <div className="bs-workspace-app-surface">
        <iframe className="bs-workspace-app-frame" src={activeApp.frontend_mount} title={`${activeApp.name} viewport`} />
      </div>
    </section>
  );
}
