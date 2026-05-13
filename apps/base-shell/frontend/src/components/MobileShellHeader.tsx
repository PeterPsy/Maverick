import type { AppRegistryItem } from "../api";
import { AppLogo } from "./AppLogo";

const SIDEBAR_DESKTOP_LOGO_SRC = "/apps/base-shell/sidebar-logo.svg";

export function MobileShellHeader({
  activeApp,
  isPrimaryActionAvailable,
  isSidebarOpen,
  onOpenNewChat,
  onOpenSidebar,
  onPrimaryAction,
  primaryActionLabel,
}: {
  activeApp: AppRegistryItem | null;
  isPrimaryActionAvailable: boolean;
  isSidebarOpen: boolean;
  onOpenNewChat: () => void;
  onOpenSidebar: () => void;
  onPrimaryAction: () => void;
  primaryActionLabel: string;
}) {
  const actionLabel = primaryActionLabel || "Azione principale";

  return (
    <header className={`bs-mobile-shell-header ${isSidebarOpen ? "is-obscured" : ""}`} aria-label="Mobile shell navigation">
      <button
        aria-label="Apri sidebar"
        className="bs-mobile-shell-header__button bs-mobile-shell-header__app"
        onClick={onOpenSidebar}
        type="button"
      >
        {activeApp ? (
          <AppLogo app={activeApp} className="bs-app-logo--rail bs-mobile-shell-header__app-logo" />
        ) : (
          <span aria-hidden="true" className="bs-app-logo is-glyph bs-app-logo--rail bs-mobile-shell-header__app-placeholder">
            <span className="material-symbols-rounded">apps</span>
          </span>
        )}
      </button>
      <button
        aria-label="Nuova chat"
        className="bs-mobile-shell-header__logo-button"
        onClick={onOpenNewChat}
        title="Nuova chat"
        type="button"
      >
        <img alt="Maverick" className="bs-mobile-shell-header__logo" src={SIDEBAR_DESKTOP_LOGO_SRC} />
      </button>
      <button
        aria-label={actionLabel}
        className="bs-mobile-shell-header__button bs-mobile-shell-header__primary-action"
        disabled={!isPrimaryActionAvailable}
        onClick={onPrimaryAction}
        title={actionLabel}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">add</span>
      </button>
    </header>
  );
}
