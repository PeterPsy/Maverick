import type { AppRegistryItem } from "../api";
import { DEFAULT_SHELL_THEME_STATE, type ShellThemeState } from "../theme";
import { AppLogo } from "./AppLogo";
import { sidebarLogoSrc } from "./sidebarLogo";

export function MobileShellHeader({
  activeApp,
  chatApp,
  isPinnedAppsOpen,
  isMobileChatOpen,
  isPrimaryActionAvailable,
  isSidebarOpen,
  showMobileChatAction,
  onCloseMobileChat,
  onOpenMobileChat,
  onOpenNewChat,
  onTogglePinnedApps,
  onToggleSidebar,
  onPrimaryAction,
  primaryActionLabel,
  shellTheme = DEFAULT_SHELL_THEME_STATE,
}: {
  activeApp: AppRegistryItem | null;
  chatApp: AppRegistryItem | null;
  isPinnedAppsOpen: boolean;
  isMobileChatOpen: boolean;
  isPrimaryActionAvailable: boolean;
  isSidebarOpen: boolean;
  showMobileChatAction: boolean;
  onCloseMobileChat: () => void;
  onOpenMobileChat: () => void;
  onOpenNewChat: () => void;
  onTogglePinnedApps: () => void;
  onToggleSidebar: () => void;
  onPrimaryAction: () => void;
  primaryActionLabel: string;
  shellTheme?: ShellThemeState;
}) {
  const actionLabel = primaryActionLabel || "Azione principale";
  const logoSrc = sidebarLogoSrc(shellTheme);

  return (
    <header className="bs-mobile-shell-header" aria-label="Mobile shell navigation">
      <div className="bs-mobile-shell-header__leading">
        <button
          aria-label={isSidebarOpen ? "Chiudi sidebar" : "Apri sidebar"}
          aria-pressed={isSidebarOpen}
          className={`bs-mobile-shell-header__button bs-mobile-shell-header__menu ${isSidebarOpen ? "is-open" : ""}`}
          onClick={onToggleSidebar}
          type="button"
        >
          <span aria-hidden="true" className="bs-mobile-shell-header__burger">
            <span />
            <span />
          </span>
        </button>
        <button
          aria-label={isPinnedAppsOpen ? "Chiudi applicazioni pinnate" : "Apri applicazioni pinnate"}
          aria-expanded={isPinnedAppsOpen}
          className="bs-mobile-shell-header__button bs-mobile-shell-header__app"
          onClick={onTogglePinnedApps}
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
      </div>
      <button
        aria-label="Nuova chat"
        className="bs-mobile-shell-header__logo-button"
        onClick={onOpenNewChat}
        title="Nuova chat"
        type="button"
      >
        <img alt="Maverick" className="bs-mobile-shell-header__logo" src={logoSrc} />
      </button>
      <div className="bs-mobile-shell-header__actions">
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
        {showMobileChatAction ? (
          <button
            aria-label={isMobileChatOpen ? "Chiudi chat contestuale" : "Apri chat contestuale"}
            aria-pressed={isMobileChatOpen}
            className={`bs-mobile-shell-header__button bs-mobile-shell-header__chat-action ${isMobileChatOpen ? "is-open" : ""}`}
            onClick={isMobileChatOpen ? onCloseMobileChat : onOpenMobileChat}
            title={isMobileChatOpen ? "Chiudi chat" : "Chat contestuale"}
            type="button"
          >
            {isMobileChatOpen ? (
              <span aria-hidden="true" className="material-symbols-rounded">close</span>
            ) : chatApp ? (
              <AppLogo app={chatApp} className="bs-app-logo--rail bs-mobile-shell-header__chat-logo" />
            ) : (
              <span aria-hidden="true" className="material-symbols-rounded">forum</span>
            )}
          </button>
        ) : null}
      </div>
    </header>
  );
}
