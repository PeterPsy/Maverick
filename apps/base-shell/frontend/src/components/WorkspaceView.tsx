import { AppRegistryItem } from "../api";
import { AppFrameHost } from "./AppFrameHost";
import { AppsPanel } from "./AppsPanel";

export function WorkspaceView({
  activeApp,
  activeAppParams,
  activeWorkspaceId,
  apps,
  error,
  isLoading,
  onOpenApp,
}: {
  activeApp: AppRegistryItem | null;
  activeAppParams: Record<string, string | boolean | null>;
  activeWorkspaceId: string;
  apps: AppRegistryItem[];
  error: string | null;
  isLoading: boolean;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
}) {
  if (!activeApp) {
    return (
      <AppsPanel
        apps={apps}
        error={error}
        isLoading={isLoading}
        onOpenApp={onOpenApp}
      />
    );
  }
  return <AppFrameHost activeApp={activeApp} activeAppParams={activeAppParams} activeWorkspaceId={activeWorkspaceId} onOpenApp={onOpenApp} />;
}
