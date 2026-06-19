import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { sidebarRailButtonClassName } from "../src/components/Sidebar";
import { calculateSidebarRailMetrics } from "../src/lib/sidebarRailMetrics";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string): string {
  return readFileSync(resolve(currentDir, "../src/styles", filename), "utf8");
}

function readSource(filename: string): string {
  return readFileSync(resolve(currentDir, "../src", filename), "utf8");
}

describe("Sidebar app rail", () => {
  it("marks the active rail app without adding runtime busy chrome", () => {
    expect(sidebarRailButtonClassName("chat", "chat")).toContain("is-active");
    expect(sidebarRailButtonClassName("chat", "chat")).not.toContain("is-busy");
  });

  it("sizes loading skeletons with the same rail logo contract as real apps", () => {
    const railSource = readSource("components/SidebarAppRail.tsx");

    expect(railSource).toContain("bs-app-logo bs-app-logo--rail bs-sidebar__rail-skeleton-logo");
  });
});

describe("Sidebar mobile layout contract", () => {
  it("uses the app background token for the detail layer", () => {
    const responsiveStyles = readStyle("responsive.css");
    const mobileDetailsRule = responsiveStyles.match(/\.bs-sidebar__details \{[\s\S]*?\n  \}/)?.[0] ?? "";

    expect(mobileDetailsRule).toContain("background: var(--maverick-bg);");
    expect(mobileDetailsRule).not.toContain("rgb(12, 12, 14)");
  });
});

describe("Sidebar desktop layout contract", () => {
  it("reserves desktop app rail space separately from fixed sidebar details", () => {
    const layoutStyles = readStyle("layout.css");
    const panelsStyles = readStyle("panels.css");
    const sidebarStyles = readStyle("sidebar.css");
    const railLayoutRule = sidebarStyles.match(/\.bs-sidebar__rail \{\n  display: flex;[\s\S]*?\n\}/)?.[0] ?? "";
    const railAppsRule = sidebarStyles.match(/\.bs-sidebar__rail-apps \{[\s\S]*?\n\}/)?.[0] ?? "";
    const railButtonRule = sidebarStyles.match(/\.bs-sidebar__rail-button \{[\s\S]*?\n\}/)?.[0] ?? "";
    const railLogoRule = sidebarStyles.match(/\.bs-app-logo--rail \{\n  width:[\s\S]*?\n\}/)?.[0] ?? "";

    expect(layoutStyles).toContain("--bs-shell-desktop-rail-space");
    expect(layoutStyles).toContain(".bs-shell:not(.is-mobile-layout) .bs-workspace-view-shell");
    expect(layoutStyles).toContain("margin-left: var(--bs-shell-desktop-rail-space);");
    expect(layoutStyles).toContain(".bs-shell.is-sidebar-mode-fixed:not(.is-mobile-layout) .bs-workspace-view-shell");
    expect(layoutStyles).toContain("margin-left: var(--bs-shell-desktop-fixed-sidebar-space);");
    expect(panelsStyles).not.toContain("calc(var(--maverick-sidebar-width) + 2rem)");
    expect(sidebarStyles).toContain("left: var(--bs-sidebar-desktop-rail-left, 1rem);");
    expect(railLayoutRule).toContain("max-height: calc(100dvh - 2rem);");
    expect(railLayoutRule).not.toContain("min(38rem");
    expect(railAppsRule).toContain("gap: 0.48rem;");
    expect(railButtonRule).toContain("width: var(--bs-sidebar-icon-size, 2.4rem);");
    expect(railLogoRule).toContain("width: var(--bs-sidebar-icon-size, 2.4rem);");
    expect(panelsStyles).toContain("width: var(--bs-sidebar-icon-size, 2.4rem);");
  });

  it("keeps the desktop logo inline with sidebar controls only on desktop", () => {
    const sidebarSource = readSource("components/Sidebar.tsx");
    const logoSource = readSource("components/sidebarLogo.ts");
    const sidebarStyles = readStyle("sidebar.css");
    const responsiveStyles = readStyle("responsive.css");

    expect(logoSource).toContain('SIDEBAR_LOGO_DARK_SRC = "/apps/base-shell/sidebar-logo.svg"');
    expect(logoSource).toContain('SIDEBAR_LOGO_LIGHT_SRC = "/apps/base-shell/sidebar-logo-black.svg"');
    expect(sidebarSource).toContain("const logoSrc = sidebarLogoSrc(shellTheme);");
    expect(sidebarSource).toContain('className="bs-sidebar__desktop-logo"');
    expect(sidebarSource).toContain("src={logoSrc}");
    expect(sidebarSource).toContain('className="bs-sidebar__control-cluster"');
    expect(sidebarSource).toContain("{!isMobileLayout ? (");
    expect(sidebarStyles).toContain(".bs-sidebar__desktop-logo");
    expect(sidebarStyles).toContain("flex: 1 1 0;");
    expect(sidebarStyles).toContain("width: 100%;");
    expect(sidebarStyles).toContain("transform: scale(0.8);");
    expect(sidebarStyles).toContain(".bs-sidebar__control-cluster");
    expect(sidebarStyles).toContain("justify-content: flex-end;");
    expect(responsiveStyles).toContain(".bs-sidebar__desktop-logo");
    expect(responsiveStyles).toContain("display: none;");
  });

  it("keeps the resize icon out of the fixed sidebar grid", () => {
    const sidebarStyles = readStyle("sidebar.css");
    const resizeRule = sidebarStyles.match(/\.bs-sidebar__resize-handle \{[\s\S]*?\n\}/)?.[0] ?? "";
    const resizeIconRule = sidebarStyles.match(/\.bs-sidebar__resize-handle \.material-symbols-rounded \{[\s\S]*?\n\}/)?.[0] ?? "";
    const fixedResizeRule = sidebarStyles.match(/\.bs-shell\.is-sidebar-mode-fixed:not\(\.is-mobile-layout\) \.bs-sidebar__resize-handle \{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(sidebarStyles).toContain(".bs-sidebar__resize-handle");
    expect(resizeRule).toContain("top: 0;");
    expect(resizeRule).toContain("bottom: 0;");
    expect(resizeRule).toContain("cursor: none;");
    expect(resizeIconRule).toContain("top: var(--bs-sidebar-resize-icon-y, 50%);");
    expect(fixedResizeRule).toContain("position: absolute;");
    expect(fixedResizeRule).toContain("z-index: 12;");
  });

  it("uses a mobile shell header for sidebar open and app-owned primary actions", () => {
    const appShellSource = readSource("AppShell.tsx");
    const headerSource = readSource("components/MobileShellHeader.tsx");
    const layoutStyles = readStyle("layout.css");
    const headerRule = layoutStyles.match(/\.bs-mobile-shell-header \{[\s\S]*?\n\}/)?.[0] ?? "";
    const statusBarRule = layoutStyles.match(/\.bs-shell\.is-mobile-layout::before \{[\s\S]*?\n\}/)?.[0] ?? "";
    const headerAppLogoRule = layoutStyles.match(/\.bs-mobile-shell-header \.bs-app-logo\.bs-app-logo--rail \{[\s\S]*?\n\}/)?.[0] ?? "";
    const mobileWorkspaceRule = layoutStyles.match(/\.bs-shell\.is-mobile-layout \.bs-workspace-view-shell \{[\s\S]*?\n\}/)?.[0] ?? "";
    const mobileAppGridRule = readStyle("panels.css").match(/\.bs-shell\.is-mobile-layout \.bs-app-grid-panel,[\s\S]*?\n\}/)?.[0] ?? "";

    expect(appShellSource).toContain("<MobileShellHeader");
    expect(appShellSource).toContain("<FloatingChatHost");
    expect(appShellSource).not.toContain("<MobileChatPanel");
    expect(appShellSource).not.toContain("<RightDockPanel");
    expect(appShellSource).not.toContain("<ShellOverlayWidgets");
    expect(appShellSource).toContain("<MobilePinnedAppsPanel");
    expect(appShellSource).toContain("mobilePrimaryActionRequestId");
    expect(appShellSource).toContain("newChatRouteParams()");
    expect(appShellSource).toContain("onOpenMobileChat={openMobileChatPanel}");
    expect(appShellSource).toContain("onCloseMobileChat={closeMobileChatPanel}");
    expect(appShellSource).toContain("showMobileChatAction={!isChatAppActive}");
    expect(appShellSource).toContain("onOpenNewChat={openNewChat}");
    expect(appShellSource).toContain("onToggleSidebar={toggleMobileSidebar}");
    expect(appShellSource).toContain("onTogglePinnedApps={toggleMobilePinnedApps}");
    expect(appShellSource).toContain("shellTheme={shellTheme}");
    expect(headerSource).toContain("const logoSrc = sidebarLogoSrc(shellTheme);");
    expect(headerSource).toContain("src={logoSrc}");
    expect(headerSource).toContain('aria-label={isSidebarOpen ? "Chiudi sidebar" : "Apri sidebar"}');
    expect(headerSource).toContain('aria-label={isPinnedAppsOpen ? "Chiudi applicazioni pinnate" : "Apri applicazioni pinnate"}');
    expect(headerSource).toContain('aria-label="Nuova chat"');
    expect(headerSource).toContain('"Apri chat contestuale"');
    expect(headerSource).toContain('"Chiudi chat contestuale"');
    expect(headerSource).toContain('className="bs-app-logo--rail bs-mobile-shell-header__app-logo"');
    expect(headerSource).toContain('className="bs-app-logo--rail bs-mobile-shell-header__chat-logo"');
    expect(headerSource).toContain("bs-mobile-shell-header__burger");
    expect(headerSource).not.toContain("<span />\n            <span />\n            <span />");
    expect(headerSource).toContain("bs-mobile-shell-header__logo-button");
    expect(headerSource).toContain("bs-mobile-shell-header__primary-action");
    expect(headerSource).toContain("bs-mobile-shell-header__chat-action");
    expect(layoutStyles).toContain(".bs-mobile-shell-header");
    expect(layoutStyles).toContain(".bs-mobile-pinned-apps");
    expect(layoutStyles).toContain(".bs-floating-chat-host.is-mobile-fullscreen");
    expect(layoutStyles).toContain("top: var(--bs-mobile-shell-content-top-offset);");
    expect(layoutStyles).toContain("transform: translateX(-100%);");
    expect(layoutStyles).not.toContain(".bs-mobile-shell-header__chat-action.is-open");
    expect(layoutStyles).toContain("--bs-mobile-shell-status-bar-height: env(safe-area-inset-top, 0px);");
    expect(layoutStyles).toContain("--bs-mobile-shell-header-height: 2.75rem;");
    expect(layoutStyles).toContain("var(--bs-mobile-shell-status-bar-height) +");
    expect(statusBarRule).toContain("height: var(--bs-mobile-shell-status-bar-height);");
    expect(statusBarRule).toContain("background: var(--maverick-mobile-safe-area-fade);");
    expect(headerRule).toContain("top: var(--bs-mobile-shell-status-bar-height);");
    expect(headerRule).toContain("z-index: 46;");
    expect(headerRule).toContain("border: 0;");
    expect(headerRule).toContain("background: transparent;");
    expect(headerRule).toContain("box-shadow: none;");
    expect(headerRule).not.toContain("backdrop-filter");
    expect(headerAppLogoRule).toContain("border: 0;");
    expect(headerAppLogoRule).toContain("background: transparent;");
    expect(headerAppLogoRule).toContain("box-shadow: none;");
    expect(mobileWorkspaceRule).toContain("padding-top: 0;");
    expect(layoutStyles).toContain(".bs-mobile-pinned-apps__button.is-active .bs-mobile-pinned-apps__logo.bs-app-logo");
    expect(layoutStyles).toContain(".bs-mobile-pinned-apps__button.is-active .bs-mobile-pinned-apps__name");
    expect(layoutStyles).toContain("background: transparent;");
    expect(layoutStyles).toContain("border-color: rgba(var(--maverick-contrast-rgb), 0.88);");
    expect(mobileAppGridRule).toContain("padding-top: calc(var(--bs-mobile-shell-content-top-offset) + 2rem);");
  });

  it("keeps the contextual chat iframe mounted while the shell changes placement", () => {
    const appShellSource = readSource("AppShell.tsx");
    const hostSource = readSource("components/FloatingChatHost.tsx");
    const widgetSlotSource = readSource("components/WidgetSlot.tsx");
    const layoutStyles = readStyle("layout.css");
    const overlayHostRule = layoutStyles.match(/\.bs-floating-chat-host\.is-overlay \{[\s\S]*?\n\}/)?.[0] ?? "";
    const overlaySlotRule = layoutStyles.match(/\.bs-floating-chat-host\.is-overlay \.bs-widget-slot--overlay \{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(appShellSource).toContain("<FloatingChatHost");
    expect(hostSource).toContain('const contentKind = isDockMode');
    expect(hostSource).toContain('"shell.overlay.bottomright"');
    expect(hostSource).toContain("contentKind={contentKind}");
    expect(hostSource).toContain("mode: placement");
    expect(hostSource).toContain("size={widgetSize}");
    expect(layoutStyles).toContain(".bs-floating-chat-host__resize-handle");
    expect(overlayHostRule).toContain("inset: 0;");
    expect(overlayHostRule).toContain("width: auto;");
    expect(overlayHostRule).toContain("height: auto;");
    expect(overlaySlotRule).toContain("position: fixed;");
    expect(overlaySlotRule).toContain("right: 0;");
    expect(overlaySlotRule).toContain("bottom: calc(env(safe-area-inset-bottom, 0px) + 1rem);");
    expect(layoutStyles).toContain(".bs-shell.is-sidebar-mode-fixed:not(.is-mobile-layout) .bs-floating-chat-host.is-overlay");
    expect(layoutStyles).toContain("pointer-events: auto;");
    expect(widgetSlotSource).toContain(
      "[activeWorkspaceId, contentKind, hostAppId, onPrimaryActionStateChange, preferredOwnerAppId, supportsPrimaryActionSlot]",
    );
    expect(widgetSlotSource).not.toContain(
      "[activeWorkspaceId, contentKind, hostAppId, onPrimaryActionStateChange, preferredOwnerAppId, size, supportsPrimaryActionSlot]",
    );
  });

  it("removes the mobile sidebar rail and reserves header space", () => {
    const sidebarSource = readSource("components/Sidebar.tsx");
    const sidebarStyles = readStyle("sidebar.css");
    const responsiveStyles = readStyle("responsive.css");

    expect(sidebarSource).not.toContain("bs-sidebar__mobile-apps");
    expect(sidebarStyles).not.toContain(".bs-sidebar__mobile-apps");
    expect(responsiveStyles).not.toContain(".bs-sidebar__mobile-apps");
    expect(responsiveStyles).toContain("calc(var(--bs-mobile-shell-content-top-offset) + 0.75rem)");
  });
});

describe("Sidebar desktop rail metrics", () => {
  it("keeps the preferred icon size while the rail fits the viewport", () => {
    const metrics = calculateSidebarRailMetrics({
      itemCount: 8,
      rootFontSizePx: 16,
      viewportHeightPx: 900,
    }) as Record<string, string>;

    expect(metrics["--bs-sidebar-icon-size"]).toBe("2.4rem");
    expect(metrics["--bs-sidebar-rail-apps-overflow-y"]).toBe("visible");
  });

  it("does not shrink icons at the old fixed rail height when the viewport has room", () => {
    const metrics = calculateSidebarRailMetrics({
      itemCount: 14,
      rootFontSizePx: 16,
      viewportHeightPx: 900,
    }) as Record<string, string>;

    expect(metrics["--bs-sidebar-icon-size"]).toBe("2.4rem");
    expect(metrics["--bs-sidebar-rail-apps-overflow-y"]).toBe("visible");
  });

  it("shrinks icons only after the rail reaches the viewport height limit", () => {
    const metrics = calculateSidebarRailMetrics({
      itemCount: 8,
      rootFontSizePx: 16,
      viewportHeightPx: 380,
    }) as Record<string, string>;
    const iconSize = Number.parseFloat(metrics["--bs-sidebar-icon-size"]);

    expect(iconSize).toBeLessThan(2.4);
    expect(iconSize).toBeGreaterThan(2.05);
    expect(metrics["--bs-sidebar-rail-apps-overflow-y"]).toBe("visible");
  });

  it("uses the minimum icon size and scrolls when the minimum cannot fit", () => {
    const metrics = calculateSidebarRailMetrics({
      itemCount: 20,
      rootFontSizePx: 16,
      viewportHeightPx: 420,
    }) as Record<string, string>;

    expect(metrics["--bs-sidebar-icon-size"]).toBe("2.05rem");
    expect(metrics["--bs-sidebar-rail-apps-overflow-y"]).toBe("auto");
  });
});
