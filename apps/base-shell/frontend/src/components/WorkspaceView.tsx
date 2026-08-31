import { AppRegistryItem } from "../api";
import type { ShellThemeState } from "../theme";
import { AppFrameHost } from "./AppFrameHost";
import { AppsPanel } from "./AppsPanel";

export function WorkspaceView({
  activeApp,
  activeAppParams,
  activeWorkspaceId,
  apps,
  cacheUserId,
  error,
  isLoading,
  isMobileLayout,
  onOpenApp,
  sessionExpiresAt,
  shellTheme,
}: {
  activeApp: AppRegistryItem | null;
  activeAppParams: Record<string, string | boolean | null>;
  activeWorkspaceId: string;
  apps: AppRegistryItem[];
  cacheUserId: string;
  error: string | null;
  isLoading: boolean;
  isMobileLayout: boolean;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  sessionExpiresAt: string;
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
      cacheUserId={cacheUserId}
      isMobileLayout={isMobileLayout}
      onOpenApp={onOpenApp}
      sessionExpiresAt={sessionExpiresAt}
      shellTheme={shellTheme}
    />
  );
}
