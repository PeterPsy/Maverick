import { AppRegistryItem, SessionUser, WorkspaceItem } from "../api";
import { BrandMark } from "./BrandMark";
import { WidgetSlot } from "./WidgetSlot";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

export function Sidebar({
  activeAppId,
  apps,
  activeWorkspaceId,
  isOpen,
  onClose,
  onOpenApp,
  onOpenApps,
  onOpenSettings,
  onOpenTutorial,
  onWorkspaceChanged,
  user,
  workspaces,
}: {
  activeAppId: string | null;
  apps: AppRegistryItem[];
  activeWorkspaceId: string;
  isOpen: boolean;
  onClose: () => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onOpenApps: () => void;
  onOpenSettings: () => void;
  onOpenTutorial: () => void;
  onWorkspaceChanged: () => void;
  user: SessionUser | null;
  workspaces: WorkspaceItem[];
}) {
  return (
    <aside className={`bs-sidebar ${isOpen ? "is-open" : "is-closed"}`} aria-hidden={!isOpen} aria-label="Workspace navigation">
      <div className="bs-sidebar__header">
        <div className="bs-sidebar__brand">
          <BrandMark className="bs-sidebar__brand-mark" />
          <div>
            <p className="bs-eyebrow">Workspace</p>
            <h1 className="bs-sidebar__title">Maverick</h1>
          </div>
        </div>
        <button aria-label="Chiudi pannello laterale" className="bs-panel-minimize" onClick={onClose} type="button">
          <span aria-hidden="true" className="material-symbols-rounded">chevron_left</span>
        </button>
      </div>

      <nav className="bs-sidebar__nav-list" aria-label="Primary navigation">
        <WorkspaceSwitcher
          activeWorkspaceId={activeWorkspaceId}
          canCreateWorkspace={user?.platform_role === "admin"}
          onChanged={onWorkspaceChanged}
          workspaces={workspaces}
        />

        <button className={`bs-sidebar__nav-button ${activeAppId === "app-store" ? "is-active" : ""}`} onClick={onOpenApps} type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">
              <span aria-hidden="true" className="material-symbols-rounded">apps</span>
            </span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Apps</span>
            </span>
          </span>
        </button>
      </nav>

      <WidgetSlot
        activeWorkspaceId={activeWorkspaceId}
        content={{ apps: apps.map((app) => app.app_id), user: user?.username || null }}
        contentKind="shell.sidebar.apps"
        hostAppId="base-shell"
        label="Pinned app shortcuts"
        onOpenApp={onOpenApp}
        size="compact"
      />

      <WidgetSlot
        activeWorkspaceId={activeWorkspaceId}
        content={{ user: user?.username || null }}
        contentKind="shell.sidebar.primary"
        hostAppId="base-shell"
        label="Chat projects and conversations"
        onOpenApp={onOpenApp}
      />

      <div className="bs-sidebar__footer">
        <button className="bs-sidebar__nav-button" onClick={onOpenTutorial} type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">
              <span aria-hidden="true" className="material-symbols-rounded">help</span>
            </span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Tutorial</span>
            </span>
          </span>
        </button>
        <button className="bs-sidebar__nav-button" onClick={onOpenSettings} type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">
              <span aria-hidden="true" className="material-symbols-rounded">settings</span>
            </span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Settings</span>
            </span>
          </span>
        </button>
      </div>
    </aside>
  );
}
