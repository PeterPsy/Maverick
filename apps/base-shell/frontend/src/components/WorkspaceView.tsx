import { AppRegistryItem } from "../api";
import type { ShellThemeState } from "../theme";
import { AppFrameHost } from "./AppFrameHost";
import { AppsPanel } from "./AppsPanel";

export function WorkspaceView({
  activeApp,
  activeAppParams,
  activeWorkspaceId,
  apps,
  error,
  isLoading,
  isMobileLayout,
  onOpenApp,
  onWorkspaceFocusChange,
  shellTheme,
}: {
  activeApp: AppRegistryItem | null;
  activeAppParams: Record<string, string | boolean | null>;
  activeWorkspaceId: string;
  apps: AppRegistryItem[];
  error: string | null;
  isLoading: boolean;
  isMobileLayout: boolean;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onWorkspaceFocusChange?: (appId: string, active: boolean) => void;
  shellTheme: ShellThemeState;
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
  return (
    <AppFrameHost
      activeApp={activeApp}
      activeAppParams={activeAppParams}
      activeWorkspaceId={activeWorkspaceId}
      isMobileLayout={isMobileLayout}
      onOpenApp={onOpenApp}
      onWorkspaceFocusChange={onWorkspaceFocusChange}
      shellTheme={shellTheme}
    />
  );
}
