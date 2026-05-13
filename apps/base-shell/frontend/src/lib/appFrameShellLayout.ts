const MOBILE_SHELL_STATUS_BAR_HEIGHT = "env(safe-area-inset-top, 0px)";
const MOBILE_SHELL_HEADER_HEIGHT = "2.75rem";
const MOBILE_SHELL_CONTENT_TOP_OFFSET = `calc(${MOBILE_SHELL_STATUS_BAR_HEIGHT} + ${MOBILE_SHELL_HEADER_HEIGHT})`;

const SHELL_LAYOUT_ATTRIBUTE = "data-maverick-shell-mobile-layout";
const SHELL_LAYOUT_PROPERTIES = [
  "--maverick-shell-mobile-status-bar-height",
  "--maverick-shell-mobile-header-height",
  "--maverick-shell-mobile-content-top-offset",
];

export function syncAppFrameShellLayout(frame: HTMLIFrameElement | null | undefined, isMobileLayout: boolean): boolean {
  const root = frame?.contentDocument?.documentElement;
  if (!root) {
    return false;
  }

  if (!isMobileLayout) {
    root.removeAttribute(SHELL_LAYOUT_ATTRIBUTE);
    for (const property of SHELL_LAYOUT_PROPERTIES) {
      root.style.removeProperty(property);
    }
    return true;
  }

  root.setAttribute(SHELL_LAYOUT_ATTRIBUTE, "true");
  root.style.setProperty("--maverick-shell-mobile-status-bar-height", MOBILE_SHELL_STATUS_BAR_HEIGHT);
  root.style.setProperty("--maverick-shell-mobile-header-height", MOBILE_SHELL_HEADER_HEIGHT);
  root.style.setProperty("--maverick-shell-mobile-content-top-offset", MOBILE_SHELL_CONTENT_TOP_OFFSET);
  return true;
}
