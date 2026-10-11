import { useRef } from "react";
import { AppRegistryItem } from "../api";
import type { MaverickFrameScope } from "../iframePolicy";
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
  frameScope,
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
  frameScope: MaverickFrameScope;
  isLoading: boolean;
  isMobileLayout: boolean;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  sessionExpiresAt: string;
  shellTheme: ShellThemeState;
}) {
  const scopeKey = `${frameScope.sessionGeneration}:${activeWorkspaceId}`;
  const last = useRef<{ scope: string; app: AppRegistryItem; params: typeof activeAppParams } | null>(null);
  if (last.current?.scope !== scopeKey) last.current = null;
  if (activeApp) last.current = { scope: scopeKey, app: activeApp, params: activeAppParams };
  const retained = last.current;
  return <>
    {!activeApp && <AppsPanel apps={apps} error={error} isLoading={isLoading} onOpenApp={onOpenApp} />}
    {retained && <AppFrameHost
      activeApp={retained.app}
      activeAppParams={retained.params}
      visible={Boolean(activeApp)}
      activeWorkspaceId={activeWorkspaceId}
      cacheUserId={cacheUserId}
      frameScope={frameScope}
      isMobileLayout={isMobileLayout}
      onOpenApp={onOpenApp}
      sessionExpiresAt={sessionExpiresAt}
      shellTheme={shellTheme}
    />}
  </>;
}
