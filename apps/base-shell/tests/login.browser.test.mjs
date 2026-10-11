import assert from "node:assert/strict";
import { test } from "node:test";
import { browserExecutable, close, listen } from "./browser-contract-support.mjs";
import { chromium, fixtureServer } from "./shell-presentation-fixture.mjs";

// Exercise the mounted build and native browser handoff without contacting Google.
test("login requests app services, recovers cancelled consent and fits desktop/mobile server panels", { timeout: 45_000 }, async () => {
  const server = fixtureServer([]);
  const origin = await listen(server);
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined, args: ["--no-sandbox"] });
    for (const viewport of [{ width: 1440, height: 950 }, { width: 390, height: 650 }]) {
      const context = await browser.newContext({ viewport, serviceWorkers: "block", reducedMotion: "reduce", colorScheme: "light" });
      await context.addInitScript(() => {
        window.webkit = { messageHandlers: {
          maverickExternalURL: { postMessage: async () => true },
          maverickServers: { postMessage: async () => ({ profiles: [{ id: "current", name: "This Maverick", origin: location.origin, current: true }] }) },
        } };
      });
      await context.route("**/api/session", route => route.fulfill({ json: { authenticated: false } }));
      await context.route("**/api/auth/google/status", route => route.fulfill({ json: {
        configured: true, services: [], login_services: ["calendar", "gmail", "drive"], registration_enabled: true,
      } }));
      let start;
      let cancelled = 0;
      await context.route("**/api/auth/google/start", route => {
        start = route.request().postDataJSON();
        return route.fulfill({ json: { browser_url: `${origin}/?google_handoff=1#fake-handoff`, flow_id: "a".repeat(64) } });
      });
      await context.route("**/api/auth/google/result", route => route.fulfill({ json: { status: "pending" } }));
      await context.route("**/api/auth/google/cancel", route => { cancelled++; return route.fulfill({ json: { status: "cancelled" } }); });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(origin);
      await page.getByRole("heading", { name: "Welcome back." }).waitFor();
      const google = page.getByRole("button", { name: "Continue with Google", exact: true });
      await google.waitFor({ state: "visible" });
      assert.equal(await page.getByRole("list", { name: "Google services requested at sign-in" }).getByRole("listitem").count(), 3);
      assert.equal(await page.getByRole("checkbox").count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      if (process.env.MAVERICK_ACCOUNT_PANEL_SCREENSHOTS) await page.screenshot({ path: `/tmp/maverick-login-${viewport.width}.png`, fullPage: true });
      await google.click();
      await page.getByRole("button", { name: "Cancel Google sign-in", exact: true }).waitFor();
      assert.deepEqual(start, { mode: "login", services: ["calendar", "gmail", "drive"], transport: "system-browser" });
      await page.getByRole("button", { name: "Cancel Google sign-in", exact: true }).click();
      assert.equal(await google.isEnabled(), true);
      await page.waitForFunction(() => !document.querySelector(".bs-login__pending"));
      assert.equal(cancelled, 1);
      await page.getByRole("button", { name: "Servers", exact: true }).click();
      const panel = page.getByRole("dialog", { name: "Servers", exact: true });
      await panel.getByRole("heading", { name: "Saved connections" }).waitFor();
      const box = await panel.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= viewport.width);
      assert.ok(box.y >= 0 && box.y + box.height <= viewport.height);
      assert.equal(await panel.evaluate(element => element.scrollWidth > element.clientWidth), false);
      await panel.getByLabel("Name", { exact: true }).fill("Offline test server");
      await panel.getByLabel("Server address", { exact: true }).fill("http://offline.example");
      await panel.getByRole("button", { name: "Add server", exact: true }).click();
      await panel.getByRole("alert").filter({ hasText: "HTTPS" }).waitFor();
      if (process.env.MAVERICK_ACCOUNT_PANEL_SCREENSHOTS) await page.screenshot({ path: `/tmp/maverick-servers-${viewport.width}.png` });
      await page.keyboard.press("Escape");
      await panel.waitFor({ state: "hidden" });
      await page.waitForFunction(() => document.activeElement?.matches(".bs-server-launcher"));
      // Password login remains available, with keyboard focus moving to the password.
      await page.getByLabel("Email or username", { exact: true }).fill("admin");
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      assert.equal(await page.getByLabel("Password", { exact: true }).evaluate(element => element === document.activeElement), true);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser?.close(); await close(server); }
});
