import { describe, expect, it } from "vitest";
import { AppRegistryItem } from "../src/api";
import {
  initialShellLaunchRoute,
  isInitialChatLaunchRoute,
  newChatRouteParams,
  parseShellAppRoute,
  preferredActiveApp,
  resolveAppOpenParams,
  shellAppPath,
  shellAppRailApps,
  shellVisibleApps,
  TRANSIENT_APP_COMMAND_PARAMS,
} from "../src/navigation";

function app(app_id: string, frontend_mount: string): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount,
    frontend_role: frontend_mount ? "workspace" : "none",
    frontend_launchable: Boolean(frontend_mount),
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
  app("settings", "/apps/settings/"),
  app("chat", "/apps/chat/"),
  app("docs", "/apps/docs/"),
  app("headless", ""),
];

describe("base-shell navigation", () => {
  it("shows only mountable non-shell apps", () => {
    expect(shellVisibleApps(registry).map((item) => item.app_id)).toEqual(["app-store", "settings", "chat", "docs"]);
  });

  it("keeps static App Store and Settings shortcuts out of reorderable pinned entries", () => {
    expect(shellAppRailApps(registry, ["chat"]).map((item) => item.app_id)).toEqual(["chat", "app-store"]);
    expect(shellAppRailApps(registry, ["settings", "app-store", "chat"]).map((item) => item.app_id)).toEqual(["chat", "app-store"]);
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
    expect(shellAppPath("agents", { new_agent: true, new_agent_request_id: "request-2" })).toBe("/app/agents");
    expect(shellAppPath("skills", { new_skill: true, new_skill_request_id: "request-3" })).toBe("/app/skills");
    expect(shellAppPath("memory", { new_node: true, new_node_request_id: "request-4" })).toBe("/app/memory");
    expect(shellAppPath("memory", { preview_context: true, preview_context_request_id: "request-5" })).toBe("/app/memory");
  });

  it("keeps mobile command params in the explicit transient set", () => {
    expect(Array.from(TRANSIENT_APP_COMMAND_PARAMS).sort()).toEqual([
      "new_agent",
      "new_agent_request_id",
      "new_chat",
      "new_chat_request_id",
      "new_node",
      "new_node_request_id",
      "new_skill",
      "new_skill_request_id",
      "open_settings_request_id",
      "open_tools_request_id",
      "preview_context",
      "preview_context_request_id",
      "settings_section",
    ]);
  });

  it("preserves source project context for same-app panel commands only", () => {
    const current = { od_project_id: "od_project_1", od_run_id: "od_run_1", view: "canvas" };

    expect(resolveAppOpenParams(
      "design-studio",
      current,
      "design-studio",
      { open_tools_request_id: "tools-1" },
    )).toEqual({
      od_project_id: "od_project_1",
      od_run_id: "od_run_1",
      open_tools_request_id: "tools-1",
    });
    expect(resolveAppOpenParams(
      "design-studio",
      current,
      "design-studio",
      { od_project_id: "od_project_2", open_settings_request_id: "settings-1" },
    )).toEqual({
      od_project_id: "od_project_2",
      open_settings_request_id: "settings-1",
    });
    expect(resolveAppOpenParams(
      "design-studio",
      current,
      "design-studio",
      { open_settings_request_id: "settings-design-1", settings_section: "designSystems" },
    )).toEqual({
      od_project_id: "od_project_1",
      od_run_id: "od_run_1",
      open_settings_request_id: "settings-design-1",
      settings_section: "designSystems",
    });
    expect(resolveAppOpenParams("design-studio", current, "design-studio", {})).toEqual({});
    expect(resolveAppOpenParams(
      "design-studio",
      current,
      "settings",
      { open_settings_request_id: "settings-2" },
    )).toEqual({ open_settings_request_id: "settings-2" });
  });

  it("creates transient new chat navigation params", () => {
    expect(newChatRouteParams(() => "request-2")).toEqual({
      new_chat: true,
      new_chat_request_id: "request-2",
    });
  });
});
