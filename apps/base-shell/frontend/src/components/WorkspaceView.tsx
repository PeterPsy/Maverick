import { AppRegistryItem } from "../api";
import { AppFrameHost } from "./AppFrameHost";
import { AppsPanel } from "./AppsPanel";

export function WorkspaceView({
  activeApp,
  activeAppParams,
  apps,
  error,
  isLoading,
  onOpenApp,
  onTogglePinnedApp,
  pinnedAppIds,
}: {
  activeApp: AppRegistryItem | null;
  activeAppParams: Record<string, string | boolean | null>;
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
  return <AppFrameHost activeApp={activeApp} activeAppParams={activeAppParams} />;
}
