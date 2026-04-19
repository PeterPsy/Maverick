import { AppRegistryItem } from "../api";
import { pinnedApps } from "../navigation";
import { AppLogo } from "./AppLogo";
import { BrandMark } from "./BrandMark";

export function Sidebar({
  activeAppId,
  apps,
  isOpen,
  onClose,
  onOpenApp,
  onOpenApps,
  pinnedAppIds,
}: {
  activeAppId: string | null;
  apps: AppRegistryItem[];
  isOpen: boolean;
  onClose: () => void;
  onOpenApp: (appId: string) => void;
  onOpenApps: () => void;
  pinnedAppIds: string[];
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
        <button className="bs-sidebar__workspace-select" type="button">
          <span className="bs-sidebar__workspace-icon">▣</span>
          <span className="bs-sidebar__workspace-copy">
            <span className="bs-sidebar__workspace-title">Versy</span>
            <span className="bs-sidebar__workspace-subtitle">Shared · Admin access</span>
          </span>
        </button>

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

      <section className="bs-chat-list" aria-label="Project folders">
        <div className="bs-chat-folder">
          <div className="bs-chat-folder__header">
            <p className="bs-chat-folder__title">Senza progetto</p>
            <span className="bs-chat-folder__count">0</span>
          </div>
        </div>
      </section>

      <div className="bs-sidebar__footer">
        <button className="bs-sidebar__nav-button" type="button">
          <span className="bs-sidebar__nav-leading">
            <span className="bs-sidebar__nav-icon">?</span>
            <span className="bs-sidebar__nav-copy">
              <span className="bs-sidebar__nav-title">Tutorial</span>
            </span>
          </span>
        </button>
        <button className="bs-sidebar__nav-button" type="button">
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
