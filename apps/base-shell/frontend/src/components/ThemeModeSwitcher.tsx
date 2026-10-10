import type { ShellThemeMode } from "../theme";

export function ThemeModeSwitcher({
  className = "",
  onThemeModeChange,
  themeMode,
}: {
  className?: string;
  onThemeModeChange: (mode: ShellThemeMode) => void;
  themeMode: ShellThemeMode;
}) {
  const classNames = ["bs-sidebar__theme-switcher", className].filter(Boolean).join(" ");
  return (
    <div className={classNames} aria-label="Theme mode">
      <ThemeModeButton
        active={themeMode === "dark"}
        icon="dark_mode"
        label="Dark mode"
        mode="dark"
        onThemeModeChange={onThemeModeChange}
      />
      <ThemeModeButton
        active={themeMode === "light"}
        icon="light_mode"
        label="Light mode"
        mode="light"
        onThemeModeChange={onThemeModeChange}
      />
      <ThemeModeButton
        active={themeMode === "system"}
        icon="desktop_windows"
        label="System mode"
        mode="system"
        onThemeModeChange={onThemeModeChange}
      />
    </div>
  );
}

function ThemeModeButton({
  active,
  icon,
  label,
  mode,
  onThemeModeChange,
}: {
  active: boolean;
  icon: string;
  label: string;
  mode: ShellThemeMode;
  onThemeModeChange: (mode: ShellThemeMode) => void;
}) {
  return (
    <button
      aria-label={label}
      aria-pressed={active}
      className={`bs-sidebar__mode-button ${active ? "is-active" : ""}`}
      onClick={() => onThemeModeChange(mode)}
      title={label}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">{icon}</span>
    </button>
  );
}
