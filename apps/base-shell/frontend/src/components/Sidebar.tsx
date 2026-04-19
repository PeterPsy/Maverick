import { AppRegistryItem, SessionUser, WorkspaceItem } from "../api";
import { pinnedApps } from "../navigation";
import { AppLogo } from "./AppLogo";
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
  pinnedAppIds,
  user,
  workspaces,
}: {
  activeAppId: string | null;
  apps: AppRegistryItem[];
  activeWorkspaceId: string;
  isOpen: boolean;
  onClose: () => void;
  onOpenApp: (appId: string) => void;
  onOpenApps: () => void;
  onOpenSettings: () => void;
  onOpenTutorial: () => void;
  onWorkspaceChanged: () => void;
  pinnedAppIds: string[];
  user: SessionUser | null;
  workspaces: WorkspaceItem[];
}) {
  if (!isOpen) {
    return null;
  }
  const pinned = pinnedApps(apps, pinnedAppIds);
  return (
    <aside className="bs-sidebar" aria-label="Workspace navigation">
      <div className="bs-sidebar__header">
        <div className="bs-sidebar__brand">
          <BrandMark className="bs-sidebar__brand-mark" />
          <div>
            <p className="bs-eyebrow">Workspace</p>
            <h1 className="bs-sidebar__title">Maverick</h1>
          </div>
        </div>
        <button aria-label="Chiudi pannello laterale" className="bs-panel-minimize" onClick={onClose} type="button">
          <span aria-hidden="true">‹</span>
        </button>
      </div>

      <nav className="bs-sidebar__nav-list" aria-label="Primary navigation">
        <WorkspaceSwitcher activeWorkspaceId={activeWorkspaceId} onChanged={onWorkspaceChanged} workspaces={workspaces} />

        {pinned.map((app) => (
          <button
            className={`bs-sidebar__nav-button ${activeAppId === app.app_id ? "is-active" : ""}`}
            key={app.app_id}
            onClick={() => onOpenApp(app.app_id)}
            type="button"
          >
            <span className="bs-sidebar__nav-leading">
              <AppLogo app={app} className="bs-app-logo--sidebar" />
              <span className="bs-sidebar__nav-copy">
                <span className="bs-sidebar__nav-title">{app.name}</span>
              </span>
            </span>
          </button>
        ))}

        <button className={`bs-sidebar__nav-button ${activeAppId === null ? "is-active" : ""}`} onClick={onOpenApps} type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">⌘</span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Apps</span>
            </span>
          </span>
        </button>
      </nav>

      <WidgetSlot
        content={{ active_app_id: activeAppId, user: user?.username || null }}
        contentKind="shell.sidebar.primary"
        hostAppId="base-shell"
        label="Chat projects and conversations"
        onOpenApp={onOpenApp}
      />

      <div className="bs-sidebar__footer">
        <button className="bs-sidebar__nav-button" onClick={onOpenTutorial} type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">?</span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Tutorial</span>
            </span>
          </span>
        </button>
        <button className="bs-sidebar__nav-button" onClick={onOpenSettings} type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">⚙</span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Settings</span>
            </span>
          </span>
        </button>
      </div>
    </aside>
  );
}
