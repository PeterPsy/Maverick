import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { send } from "./browser-contract-support.mjs";

export const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const requireBrowser = createRequire(
  resolve(appRoot, "../browser/package.json"),
);
export const { chromium } = requireBrowser("playwright");
const apps = ["chat", "canvas", "settings"].map((app_id) => ({
  app_id,
  name: app_id,
  status: "enabled",
  frontend_role: "workspace",
  frontend_launchable: true,
  frontend_mount: `/apps/${app_id}/`,
  sidebar_enabled: app_id !== "canvas",
  provides:
    app_id === "chat"
      ? [
          {
            interface: "notifications.inbox",
            version: "1",
            surfaces: ["backend"],
          },
        ]
      : [],
  requires: [],
}));
const user = {
  user_id: "fixture-user",
  username: "fixture",
  platform_role: "admin",
  account_type: "local",
};

export function fixtureServer(requests, feed) {
  let notifications = structuredClone(
    feed?.notifications ?? [
      { id: "fixture-reminder", title: "Promemoria di prova" },
    ],
  );
  const capabilities = feed?.capabilities ?? {};
  return createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    requests.push(url.pathname + url.search);
    const json = (body, status = 200) =>
      send(response, JSON.stringify(body), "application/json", status);
    if (url.pathname === "/api/session")
      return json({
        authenticated: true,
        expires_at: "2099-01-01T00:00:00Z",
        session_generation: "fixture-session",
        workspace_id: "default",
        user,
      });
    if (url.pathname === "/api/apps") return json({ items: apps });
    if (url.pathname === "/api/workspaces")
      return json({
        items: [
          {
            workspace_id: "default",
            name: "Default",
            is_active: true,
            status: "active",
          },
        ],
        active_workspace_id: "default",
      });
    if (url.pathname === "/api/apps/app-store/backend")
      return json({ pinned_apps: ["chat", "canvas"] });
    if (url.pathname === "/api/apps/chat/backend") {
      let bytes = "";
      for await (const chunk of request) bytes += chunk;
      const body = JSON.parse(bytes || "{}");
      if (body.action === "notifications.dismiss") {
        notifications = notifications.filter((n) => n.id !== body.id);
        return json({ dismissed: true });
      }
      if (body.action === "notifications.read" && capabilities.read) {
        notifications = notifications.map((n) =>
          body.all || n.id === body.id ? { ...n, read: true } : n,
        );
        return json({ read: true });
      }
      if (body.action === "notifications.action" && capabilities.actions) {
        const n = notifications.find((n) => n.id === body.id);
        if (!n?.actions?.some((a) => a.id === body.action_id))
          return json({ error: "invalid_action" }, 400);
        n.action_done = n.actions.find((a) => a.id === body.action_id).done;
        n.read = true;
        return json({ notification: n });
      }
      return json({
        notifications,
        total: notifications.length,
        unread_total: notifications.filter((n) => !n.read).length,
        capabilities,
      });
    }
    if (url.pathname === "/api/settings/provider-setup")
      return json({
        provider: {
          active_provider: "fixture",
          available_providers: [],
          blocked_reason: "ready",
          model_settings: null,
          selection: null,
        },
        user,
        workspace: { workspace_id: "default" },
      });
    if (url.pathname === "/api/apps/dependencies")
      return json({
        workspace_id: "default",
        consumer_app_id: "canvas",
        status: "ready",
        dependencies: [],
      });
    if (url.pathname === "/api/apps/widgets") return json({ items: [] });
    // App documents and sidecars are outside this shell-only fixture.
    if (url.pathname.startsWith("/api/"))
      return json({ error: "fixture_surface_unavailable" }, 503);
    const assetPath = url.pathname.startsWith("/apps/base-shell/")
      ? url.pathname.slice("/apps/base-shell/".length)
      : url.pathname.startsWith("/app/") || url.pathname === "/"
        ? "index.html"
        : url.pathname.slice(1);
    const path = resolve(appRoot, "frontend/dist", assetPath);
    if (!path.startsWith(resolve(appRoot, "frontend/dist") + "/"))
      return send(response, "", "text/plain", 404);
    try {
      const mime = path.endsWith(".js")
        ? "text/javascript"
        : path.endsWith(".css")
          ? "text/css"
          : path.endsWith(".html")
            ? "text/html"
            : path.endsWith(".woff2")
              ? "font/woff2"
              : path.endsWith(".svg")
                ? "image/svg+xml"
                : path.endsWith(".png")
                  ? "image/png"
                  : "application/octet-stream";
      send(response, await readFile(path), mime);
    } catch {
      send(response, "", "text/plain", 404);
    }
  });
}
