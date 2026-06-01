import type { AppRegistryItem } from "../api";
import { AppLogo } from "./AppLogo";

export function MobilePinnedAppsPanel({
  activeAppId,
  apps,
  isOpen,
  onOpenApp,
}: {
  activeAppId: string | null;
  apps: AppRegistryItem[];
  isOpen: boolean;
  onOpenApp: (appId: string) => void;
}) {
  return (
    <section
      aria-hidden={!isOpen}
      aria-label="Applicazioni pinnate"
      className={`bs-mobile-pinned-apps ${isOpen ? "is-open" : ""}`}
    >
      <div className="bs-mobile-pinned-apps__scroller">
        <div className="bs-mobile-pinned-apps__grid" role="list">
          {apps.map((app) => (
            <div className="bs-mobile-pinned-apps__item" key={app.app_id} role="listitem">
              <button
                aria-current={activeAppId === app.app_id ? "page" : undefined}
                aria-label={app.name}
                className={`bs-mobile-pinned-apps__button ${activeAppId === app.app_id ? "is-active" : ""}`}
                onClick={() => onOpenApp(app.app_id)}
                type="button"
              >
                <AppLogo app={app} className="bs-mobile-pinned-apps__logo" />
                <span className="bs-mobile-pinned-apps__name">{app.name}</span>
              </button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
