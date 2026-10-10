import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { browserExecutable, close, listen, send } from "./browser-contract-support.mjs";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const requireBrowser = createRequire(resolve(appRoot, "../browser/package.json"));
const { chromium } = requireBrowser("playwright");
const apps = ["chat", "canvas", "settings"].map((app_id) => ({
  app_id, name: app_id, status: "enabled", frontend_role: "workspace", frontend_launchable: true,
  frontend_mount: `/apps/${app_id}/`, sidebar_enabled: app_id !== "canvas", provides: [], requires: [],
}));
const user = { user_id: "fixture-user", username: "fixture", platform_role: "admin", account_type: "local" };

function fixtureServer(requests) {
  return createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    requests.push(url.pathname + url.search);
    const json = (body, status = 200) => send(response, JSON.stringify(body), "application/json", status);
    if (url.pathname === "/api/session") return json({ authenticated: true, expires_at: "2099-01-01T00:00:00Z", session_generation: "fixture-session", workspace_id: "default", user });
    if (url.pathname === "/api/apps") return json({ items: apps });
    if (url.pathname === "/api/workspaces") return json({ items: [{ workspace_id: "default", name: "Default", is_active: true, status: "active" }], active_workspace_id: "default" });
    if (url.pathname === "/api/apps/app-store/backend") return json({ pinned_apps: ["chat", "canvas"] });
    if (url.pathname === "/api/settings/provider-setup") return json({ provider: { active_provider: "fixture", available_providers: [], blocked_reason: "ready", model_settings: null, selection: null }, user, workspace: { workspace_id: "default" } });
    if (url.pathname === "/api/apps/dependencies") return json({ workspace_id: "default", consumer_app_id: "canvas", status: "ready", dependencies: [] });
    if (url.pathname === "/api/apps/widgets") return json({ items: [] });
    // App documents and sidecars are outside this shell-only fixture.
    if (url.pathname.startsWith("/api/")) return json({ error: "fixture_surface_unavailable" }, 503);
    const assetPath = url.pathname.startsWith("/apps/base-shell/")
      ? url.pathname.slice("/apps/base-shell/".length)
      : url.pathname.startsWith("/app/") || url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    const path = resolve(appRoot, "frontend/dist", assetPath);
    if (!path.startsWith(resolve(appRoot, "frontend/dist") + "/")) return send(response, "", "text/plain", 404);
    try {
      const mime = path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css"
        : path.endsWith(".html") ? "text/html" : path.endsWith(".woff2") ? "font/woff2"
        : path.endsWith(".svg") ? "image/svg+xml" : path.endsWith(".png") ? "image/png" : "application/octet-stream";
      send(response, await readFile(path), mime);
    } catch {
      send(response, "", "text/plain", 404);
    }
  });
}

test("built shell supports app sidebar opt-out, desktop menus, saved preferences and mobile touch", { timeout: 45_000 }, async () => {
  const requests = [];
  const server = fixtureServer(requests);
  const origin = await listen(server);
  let browser;
  let lastPage;
  try {
    browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined, args: ["--no-sandbox"] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("maverick:base-shell:session", JSON.stringify({ activeAppId: "canvas", sidebarMode: "fixed", isSidebarOpen: true })));
    const page = await context.newPage();
    page.on("pageerror", (error) => console.error("Fixture page error:", error.message));
    lastPage = page;
    await page.goto(`${origin}/app/canvas`);
    const rail = page.locator(".bs-sidebar__rail");
    await rail.waitFor();
    await page.locator(".bs-sidebar--disabled").waitFor();
    assert.equal(await page.locator(".bs-shell.is-sidebar-mode-rail").count(), 1, await page.locator(".bs-shell").getAttribute("class"));
    await rail.hover();
    assert.equal(await page.locator(".bs-sidebar.is-open").count(), 0);
    assert.equal(await page.locator(".bs-sidebar__resize-handle").count(), 0);
    assert.ok((await page.locator(".bs-workspace-view-shell").boundingBox()).x < 100);
    assert.ok(!requests.some((url) => /content_kind=shell.sidebar.(primary|footer)/.test(url)));

    const top = page.getByRole("button", { name: "Controlli workspace", exact: true });
    await top.hover();
    const workspace = page.getByRole("combobox", { name: "Workspace", exact: true });
    await workspace.waitFor({ state: "visible" });
    await workspace.hover();
    assert.equal(await top.getAttribute("aria-expanded"), "true");
    const panel = await page.locator(".bs-sidebar__rail-menu-panel").boundingBox();
    assert.ok(panel.x > (await rail.boundingBox()).x);
    assert.ok(panel.x + panel.width <= 1440);
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, "sidebar-desktop.png") });
    await top.focus();
    await page.keyboard.press("Escape");
    assert.equal(await top.getAttribute("aria-expanded"), "false");

    await page.getByRole("button", { name: "Controlli Maverick", exact: true }).hover();
    await page.getByRole("button", { name: "Light mode", exact: true }).click();
    assert.equal(await page.locator("html").getAttribute("data-maverick-theme"), "light");
    await page.getByRole("button", { name: "chat. Alt+ArrowUp or Alt+ArrowDown to reorder.", exact: true }).click();
    await page.locator(".bs-shell.is-sidebar-mode-fixed").waitFor();
    await page.waitForFunction(() => document.querySelector(".bs-workspace-view-shell").getBoundingClientRect().x > 300);
    await page.getByRole("button", { name: "canvas. Alt+ArrowUp or Alt+ArrowDown to reorder.", exact: true }).click();
    await page.locator(".bs-sidebar--disabled").waitFor();
    await page.waitForFunction(() => document.querySelector(".bs-workspace-view-shell").getBoundingClientRect().x < 100);
    await context.close();

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: "block" });
    const mobilePage = await mobile.newPage();
    lastPage = mobilePage;
    await mobilePage.goto(`${origin}/app/canvas`);
    await mobilePage.getByRole("button", { name: "Apri controlli workspace", exact: true }).tap();
    await mobilePage.getByRole("combobox", { name: "Workspace", exact: true }).waitFor({ state: "visible" });
    assert.equal(await mobilePage.locator(".bs-shell.is-sidebar-open").count(), 0);
    const mobilePanel = await mobilePage.locator(".bs-sidebar__rail-menu-panel").boundingBox();
    assert.ok(mobilePanel.x >= 0 && mobilePanel.x + mobilePanel.width <= 390);
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await mobilePage.screenshot({ path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, "sidebar-mobile.png") });
    await mobilePage.getByRole("button", { name: "Light mode", exact: true }).tap();
    assert.equal(await mobilePage.locator("html").getAttribute("data-maverick-theme"), "light");
    await mobilePage.getByRole("button", { name: "Chiudi controlli workspace", exact: true }).tap();
    assert.equal(await mobilePage.locator(".bs-sidebar__rail-menu-panel").count(), 0);
    await mobile.close();
  } catch (error) {
    if (lastPage && !lastPage.isClosed()) {
      console.error("Shell fixture:", await lastPage.locator("body").innerText(), requests.filter((url) => url.startsWith("/api/")));
    }
    throw error;
  } finally {
    await browser?.close();
    await close(server);
  }
});
