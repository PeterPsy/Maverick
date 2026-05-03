import { describe, expect, it } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { sidebarMobileRailApps, sidebarRailButtonClassName } from "../src/components/Sidebar";
import { calculateSidebarRailMetrics } from "../src/lib/sidebarRailMetrics";

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
