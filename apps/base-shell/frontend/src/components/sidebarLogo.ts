import type { ShellThemeState } from "../theme";

export const SIDEBAR_LOGO_DARK_SRC = "/apps/base-shell/sidebar-logo.svg";
export const SIDEBAR_LOGO_LIGHT_SRC = "/apps/base-shell/sidebar-logo-black.svg";

export function sidebarLogoSrc(theme: ShellThemeState): string {
  return theme.effective === "light" ? SIDEBAR_LOGO_LIGHT_SRC : SIDEBAR_LOGO_DARK_SRC;
}
