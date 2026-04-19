import { AppRegistryItem } from "../api";
import { AppsPanel } from "./AppsPanel";

export function WorkspaceView({
  activeApp,
  apps,
  error,
  isLoading,
  onOpenApp,
}: {
  activeApp: AppRegistryItem | null;
  apps: AppRegistryItem[];
  error: string | null;
  isLoading: boolean;
  onOpenApp: (appId: string) => void;
}) {
  if (!activeApp) {
    return <AppsPanel apps={apps} error={error} isLoading={isLoading} onOpenApp={onOpenApp} />;
  }
  return (
    <section className="bs-workspace-app-panel" aria-label={`${activeApp.name} app`}>
      <div className="bs-workspace-app-surface">
        <iframe className="bs-workspace-app-frame" src={activeApp.frontend_mount} title={`${activeApp.name} viewport`} />
      </div>
    </section>
  );
}
