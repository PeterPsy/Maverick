import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { sidebarMobileRailApps, sidebarRailButtonClassName } from "../src/components/Sidebar";
import { calculateSidebarRailMetrics } from "../src/lib/sidebarRailMetrics";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string): string {
  return readFileSync(resolve(currentDir, "../src/styles", filename), "utf8");
}

function readSource(filename: string): string {
  return readFileSync(resolve(currentDir, "../src", filename), "utf8");
}

function app(app_id: string): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount: `/apps/${app_id}/`,
    logo: null,
    name: app_id,
    publisher: "maverick",
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    provides: [],
    requires: [],
    views: [],
  };
}

describe("Sidebar mobile app rail", () => {
  it("hides the active app from the mobile app rail", () => {
    expect(sidebarMobileRailApps([app("chat"), app("docs"), app("app-store")], "chat").map((item) => item.app_id)).toEqual([
      "docs",
      "app-store",
    ]);
  });

  it("keeps all apps when no app is active", () => {
    expect(sidebarMobileRailApps([app("chat"), app("docs")], null).map((item) => item.app_id)).toEqual(["chat", "docs"]);
  });

  it("marks the active rail app without adding runtime busy chrome", () => {
    expect(sidebarRailButtonClassName("chat", "chat")).toContain("is-active");
    expect(sidebarRailButtonClassName("chat", "chat")).not.toContain("is-busy");
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

    expect(layoutStyles).toContain("--bs-shell-desktop-rail-space");
    expect(layoutStyles).toContain(".bs-shell:not(.is-mobile-layout) .bs-workspace-view-shell");
    expect(layoutStyles).toContain("margin-left: var(--bs-shell-desktop-rail-space);");
    expect(layoutStyles).toContain(".bs-shell.is-sidebar-mode-fixed:not(.is-mobile-layout) .bs-workspace-view-shell");
    expect(layoutStyles).toContain("margin-left: var(--bs-shell-desktop-fixed-sidebar-space);");
    expect(panelsStyles).not.toContain("calc(var(--maverick-sidebar-width) + 2rem)");
    expect(sidebarStyles).toContain("left: var(--bs-sidebar-desktop-rail-left, 1rem);");
  });

  it("keeps the desktop logo inline with sidebar controls only on desktop", () => {
    const sidebarSource = readSource("components/Sidebar.tsx");
    const sidebarStyles = readStyle("sidebar.css");
    const responsiveStyles = readStyle("responsive.css");

    expect(sidebarSource).toContain('SIDEBAR_DESKTOP_LOGO_SRC = "/apps/base-shell/sidebar-logo.svg"');
    expect(sidebarSource).toContain('className="bs-sidebar__desktop-logo"');
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
    expect(appShellSource).toContain("mobilePrimaryActionRequestId");
    expect(appShellSource).toContain("newChatRouteParams()");
    expect(appShellSource).toContain("onOpenNewChat={openNewChat}");
    expect(headerSource).toContain('SIDEBAR_DESKTOP_LOGO_SRC = "/apps/base-shell/sidebar-logo.svg"');
    expect(headerSource).toContain('aria-label="Apri sidebar"');
    expect(headerSource).toContain('aria-label="Nuova chat"');
    expect(headerSource).toContain('className="bs-app-logo--rail bs-mobile-shell-header__app-logo"');
    expect(headerSource).toContain("bs-mobile-shell-header__logo-button");
    expect(headerSource).toContain("bs-mobile-shell-header__primary-action");
    expect(layoutStyles).toContain(".bs-mobile-shell-header");
    expect(layoutStyles).toContain("--bs-mobile-shell-status-bar-height: env(safe-area-inset-top, 0px);");
    expect(layoutStyles).toContain("--bs-mobile-shell-header-height: 2.75rem;");
    expect(layoutStyles).toContain("var(--bs-mobile-shell-status-bar-height) +");
    expect(statusBarRule).toContain("height: var(--bs-mobile-shell-status-bar-height);");
    expect(statusBarRule).toContain("linear-gradient(180deg, rgba(7, 7, 8, 0.92), rgba(7, 7, 8, 0.62));");
    expect(headerRule).toContain("top: var(--bs-mobile-shell-status-bar-height);");
    expect(headerRule).toContain("border: 0;");
    expect(headerRule).toContain("background: rgba(7, 7, 8, 0.5);");
    expect(headerRule).toContain("box-shadow: none;");
    expect(headerRule).toContain("backdrop-filter: blur(18px);");
    expect(headerRule).toContain("-webkit-backdrop-filter: blur(18px);");
    expect(headerAppLogoRule).toContain("border: 0;");
    expect(headerAppLogoRule).toContain("background: transparent;");
    expect(headerAppLogoRule).toContain("box-shadow: none;");
    expect(mobileWorkspaceRule).toContain("padding-top: 0;");
    expect(mobileAppGridRule).toContain("padding-top: calc(var(--bs-mobile-shell-content-top-offset) + 2rem);");
  });
});

describe("Sidebar desktop rail metrics", () => {
  it("keeps the preferred icon size while the rail fits the viewport", () => {
    const metrics = calculateSidebarRailMetrics({
      itemCount: 8,
      rootFontSizePx: 16,
      viewportHeightPx: 900,
    }) as Record<string, string>;

    expect(metrics["--bs-sidebar-icon-size"]).toBe("3rem");
    expect(metrics["--bs-sidebar-rail-apps-overflow-y"]).toBe("visible");
  });

  it("shrinks icons only after the rail reaches the viewport height limit", () => {
    const metrics = calculateSidebarRailMetrics({
      itemCount: 8,
      rootFontSizePx: 16,
      viewportHeightPx: 420,
    }) as Record<string, string>;
    const iconSize = Number.parseFloat(metrics["--bs-sidebar-icon-size"]);

    expect(iconSize).toBeLessThan(3);
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
