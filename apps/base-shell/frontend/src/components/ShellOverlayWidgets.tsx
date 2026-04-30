import type { AppRegistryItem } from "../api";
import { WidgetSlot } from "./WidgetSlot";

export function ShellOverlayWidgets({
  activeApp,
  activeWorkspaceId,
  onOpenApp,
  user,
}: {
  activeApp: AppRegistryItem | null;
  activeWorkspaceId: string;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  user: { username?: string | null } | null;
}) {
  return (
    <div className="bs-shell-overlay-widgets" aria-label="Shell overlay widgets">
      <WidgetSlot
        activeAppId={activeApp?.app_id || null}
        activeWorkspaceId={activeWorkspaceId}
        content={{
          active_app: activeApp
            ? {
                app_id: activeApp.app_id,
                description: activeApp.description,
                name: activeApp.name,
                views: activeApp.views,
              }
            : null,
          placement: "bottom-right",
          user: user?.username || null,
        }}
        contentKind="shell.overlay.bottomright"
        hostAppId="base-shell"
        label="Floating shell widget"
        onOpenApp={onOpenApp}
        size="overlay"
      />
    </div>
  );
}
