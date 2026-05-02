import { describe, expect, it } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { sidebarMobileRailApps, sidebarRailButtonClassName } from "../src/components/Sidebar";

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
