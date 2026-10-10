import type { ReactNode } from "react";
import type { AppRegistryItem, WorkspaceItem } from "../api";
import { AppLogo } from "./AppLogo";
import { BrandMark } from "./BrandMark";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

export function SidebarHeader({ activeApp, activeWorkspaceId, isLoading, isWorkspacesLoading, onOpenAppSettings, onWorkspaceChange, workspaces, notifications }: {
  activeApp: AppRegistryItem | null;
  activeWorkspaceId: string;
  isLoading: boolean;
  isWorkspacesLoading: boolean;
  onOpenAppSettings: () => void;
  onWorkspaceChange: (workspaceId: string) => Promise<void> | void;
  workspaces: WorkspaceItem[];
  notifications?: ReactNode;
}) {
  const settingsLabel = activeApp ? `Impostazioni di ${activeApp.name}` : "Impostazioni app";
  return (
    <div className="bs-sidebar__header">
      {activeApp ? <AppLogo app={activeApp} className="bs-sidebar__brand-mark" />
        : isLoading ? <span className="bs-sidebar__brand-mark bs-sidebar__brand-mark-skeleton" aria-hidden="true" />
        : <BrandMark className="bs-sidebar__brand-mark" />}
      <WorkspaceSwitcher activeWorkspaceId={activeWorkspaceId} isLoading={isWorkspacesLoading}
        onWorkspaceChange={onWorkspaceChange} workspaces={workspaces} />
      <button aria-label={settingsLabel} title={settingsLabel} className="bs-sidebar__app-settings"
        disabled={!activeApp || isLoading} onClick={onOpenAppSettings} type="button">
        <span aria-hidden="true" className="material-symbols-rounded">settings</span>
      </button>
      {notifications}
    </div>
  );
}
