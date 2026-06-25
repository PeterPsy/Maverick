import type { AppRegistryItem } from "../api";
import { AppLogo } from "./AppLogo";

const MOBILE_PINNED_APPS_SKELETON_COUNT = 4;

export function MobilePinnedAppsPanel({
  activeAppId,
  apps,
  isOpen,
  isLoading,
  onOpenApp,
  onOpenSettings,
  settingsApp,
}: {
  activeAppId: string | null;
  apps: AppRegistryItem[];
  isOpen: boolean;
  isLoading: boolean;
  onOpenApp: (appId: string) => void;
  onOpenSettings: () => void;
  settingsApp: AppRegistryItem | null;
}) {
  const panelLabel = isLoading ? "Caricamento applicazioni" : "Applicazioni";

  return (
    <section
      aria-busy={isLoading ? "true" : undefined}
      aria-hidden={!isOpen}
      aria-label={panelLabel}
      className={`bs-mobile-pinned-apps ${isOpen ? "is-open" : ""} ${isLoading ? "is-loading" : ""}`}
    >
      <div className="bs-mobile-pinned-apps__scroller">
        <div className="bs-mobile-pinned-apps__grid" role="list">
          {isLoading
            ? Array.from({ length: MOBILE_PINNED_APPS_SKELETON_COUNT }).map((_, index) => (
                <div className="bs-mobile-pinned-apps__item" key={index} role="listitem">
                  <div className="bs-mobile-pinned-apps__button bs-mobile-pinned-apps__skeleton" aria-hidden="true">
                    <span className="bs-app-logo bs-mobile-pinned-apps__logo bs-sidebar__rail-skeleton-logo bs-mobile-pinned-apps__skeleton-logo" />
                    <span className="bs-mobile-pinned-apps__skeleton-name" />
                  </div>
                </div>
              ))
            : apps.map((app) => (
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
          {!isLoading && settingsApp ? (
            <div className="bs-mobile-pinned-apps__item" role="listitem">
              <button
                aria-current={activeAppId === settingsApp.app_id ? "page" : undefined}
                aria-label={settingsApp.name}
                className={`bs-mobile-pinned-apps__button ${activeAppId === settingsApp.app_id ? "is-active" : ""}`}
                onClick={onOpenSettings}
                type="button"
              >
                <AppLogo app={settingsApp} className="bs-mobile-pinned-apps__logo" />
                <span className="bs-mobile-pinned-apps__name">{settingsApp.name}</span>
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
