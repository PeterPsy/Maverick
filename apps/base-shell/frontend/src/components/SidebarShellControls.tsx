import type { SidebarMode } from "../session";
import type { ShellThemeMode, ShellThemeState } from "../theme";
import { sidebarLogoSrc } from "./sidebarLogo";
import { ThemeModeSwitcher } from "./ThemeModeSwitcher";

export function SidebarShellControls({ mode, onModeChange, onThemeModeChange, shellTheme, themeMode, onClose }: {
  mode: SidebarMode;
  onModeChange: (mode: SidebarMode) => void;
  onThemeModeChange: (mode: ShellThemeMode) => void;
  shellTheme: ShellThemeState;
  themeMode: ShellThemeMode;
  onClose?: () => void;
}) {
  return (
    <div className="bs-sidebar__shell-controls">
      <img alt="" aria-hidden="true" className="bs-sidebar__desktop-logo" src={sidebarLogoSrc(shellTheme)} />
      <div className="bs-sidebar__control-cluster">
        <ThemeModeSwitcher onThemeModeChange={onThemeModeChange} themeMode={themeMode} />
        <div className="bs-sidebar__mode-switcher" aria-label="Sidebar mode">
          <button aria-label="Solo app in overlay" aria-pressed={mode === "rail"}
            className={`bs-sidebar__mode-button ${mode === "rail" ? "is-active" : ""}`}
            onClick={() => onModeChange("rail")} title="Solo app in overlay" type="button">
            <span aria-hidden="true" className="material-symbols-rounded">dock_to_left</span>
          </button>
          <button aria-label="Sidebar fissa" aria-pressed={mode === "fixed"}
            className={`bs-sidebar__mode-button ${mode === "fixed" ? "is-active" : ""}`}
            onClick={() => onModeChange("fixed")} title="Sidebar fissa" type="button">
            <span aria-hidden="true" className="material-symbols-rounded">left_panel_close</span>
          </button>
        </div>
        {onClose ? <button aria-label="Chiudi pannello laterale" className="bs-panel-minimize"
          onClick={onClose} title="Chiudi pannello laterale" type="button">
          <span aria-hidden="true" className="material-symbols-rounded">chevron_left</span>
        </button> : null}
      </div>
    </div>
  );
}
