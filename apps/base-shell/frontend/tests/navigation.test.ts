import { describe, expect, it } from "vitest";
import { AppRegistryItem } from "../src/api";
import { preferredActiveApp, shellVisibleApps } from "../src/navigation";

function app(app_id: string, frontend_mount: string): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount,
    logo: null,
    name: app_id,
    publisher: "maverick",
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    views: [],
  };
}

const registry = [app("base-shell", "/apps/base-shell/"), app("chat", "/apps/chat/"), app("docs", "/apps/docs/"), app("headless", "")];

describe("base-shell navigation", () => {
  it("shows only mountable non-shell apps", () => {
    expect(shellVisibleApps(registry).map((item) => item.app_id)).toEqual(["chat", "docs"]);
  });

  it("prefers requested app, then chat, then first visible app", () => {
    expect(preferredActiveApp(registry, "docs")?.app_id).toBe("docs");
    expect(preferredActiveApp(registry, "missing")?.app_id).toBe("chat");
    expect(preferredActiveApp([app("docs", "/apps/docs/")], null)?.app_id).toBe("docs");
  });
});
