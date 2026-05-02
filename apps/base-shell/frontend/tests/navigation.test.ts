import { describe, expect, it } from "vitest";
import { AppRegistryItem } from "../src/api";
import {
  initialShellLaunchRoute,
  isInitialChatLaunchRoute,
  parseShellAppRoute,
  preferredActiveApp,
  shellAppPath,
  shellAppRailApps,
  shellVisibleApps,
} from "../src/navigation";

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
    provides: [],
    requires: [],
    views: [],
  };
}

const registry = [
  app("base-shell", "/apps/base-shell/"),
  app("app-store", "/apps/app-store/"),
  app("chat", "/apps/chat/"),
  app("docs", "/apps/docs/"),
  app("headless", ""),
];

describe("base-shell navigation", () => {
  it("shows only mountable non-shell apps", () => {
    expect(shellVisibleApps(registry).map((item) => item.app_id)).toEqual(["app-store", "chat", "docs"]);
  });

  it("keeps App Store in the app rail without duplicating pinned entries", () => {
    expect(shellAppRailApps(registry, ["chat"]).map((item) => item.app_id)).toEqual(["chat", "app-store"]);
    expect(shellAppRailApps(registry, ["app-store", "chat"]).map((item) => item.app_id)).toEqual(["chat", "app-store"]);
  });

  it("prefers requested app, then App Store, then first visible app", () => {
    expect(preferredActiveApp(registry, "docs")?.app_id).toBe("docs");
    expect(preferredActiveApp(registry, "DOCS")?.app_id).toBe("docs");
    expect(preferredActiveApp(registry, "missing")?.app_id).toBe("app-store");
    expect(preferredActiveApp([app("docs", "/apps/docs/")], null)?.app_id).toBe("docs");
  });

  it("parses user-facing app routes into app id and app page params", () => {
    expect(parseShellAppRoute("/app/record-centric/Contacts/Mattia-siciliano-234512/notes/latest", "?focus=activity")).toEqual({
      appId: "record-centric",
      params: { app_page: "Contacts/Mattia-siciliano-234512/notes/latest", focus: "activity" },
    });
    expect(parseShellAppRoute("/")).toEqual({ appId: null, params: {} });
  });

  it("treats the empty shell route and empty chat route as the new chat launch screen", () => {
    expect(isInitialChatLaunchRoute(parseShellAppRoute("/"))).toBe(true);
    expect(isInitialChatLaunchRoute(parseShellAppRoute("/app/chat"))).toBe(true);
    expect(isInitialChatLaunchRoute(parseShellAppRoute("/app/chat/threads/thread-123"))).toBe(false);
    expect(isInitialChatLaunchRoute(parseShellAppRoute("/app/docs"))).toBe(false);

    expect(initialShellLaunchRoute(parseShellAppRoute("/app/chat"), () => "request-1")).toEqual({
      appId: "chat",
      params: {
        new_chat: true,
        new_chat_request_id: "request-1",
      },
    });
  });

  it("builds user-facing app routes without leaking transient command params", () => {
    expect(shellAppPath("chat", { app_page: "threads/thread-123" })).toBe("/app/chat/threads/thread-123");
    expect(shellAppPath("records", { app_page: "Contacts/Mattia-siciliano-234512/notes/latest" })).toBe(
      "/app/records/Contacts/Mattia-siciliano-234512/notes/latest",
    );
    expect(shellAppPath("chat", { new_chat: true, new_chat_request_id: "request-1", workspace_id: "acme" })).toBe("/app/chat");
  });
});
