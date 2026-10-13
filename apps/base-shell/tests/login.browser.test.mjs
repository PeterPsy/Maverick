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
    for (const { viewport, reducedMotion } of [
      { viewport: { width: 1440, height: 950 }, reducedMotion: "reduce" },
      { viewport: { width: 390, height: 650 }, reducedMotion: "reduce" },
      { viewport: { width: 320, height: 480 }, reducedMotion: "reduce" },
      { viewport: { width: 1440, height: 950 }, reducedMotion: "no-preference" },
    ]) {
      const context = await browser.newContext({ viewport, serviceWorkers: "block", reducedMotion, colorScheme: "light" });
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
      let passwordLogin;
      await context.route("**/api/auth/login", route => {
        passwordLogin = route.request().postDataJSON();
        return route.fulfill({ status: 401, json: { error: "invalid_credentials" } });
      });
      const page = await context.newPage();
      page.setDefaultTimeout(10_000);
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(origin);
      await page.getByRole("heading", { name: "Maverick was waiting for you." }).waitFor();
      const google = page.getByRole("button", { name: "Continue with Google", exact: true });
      await google.waitFor({ state: "visible" });
      assert.equal(await page.getByRole("list", { name: "Google services requested at sign-in" }).getByRole("listitem").count(), 3);
      assert.equal(await page.getByRole("checkbox").count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const fields = await page.locator(".bs-login__fields").boundingBox();
      const googleBox = await google.boundingBox();
      assert.ok(googleBox.y >= fields.y + fields.height, "Google panel must sit below the standard login");
      assert.deepEqual(await page.locator(".bs-login__content").evaluate(element => {
        const style = getComputedStyle(element);
        return [style.backgroundColor, style.borderTopWidth, style.boxShadow];
      }), ["rgba(0, 0, 0, 0)", "0px", "none"], "Login must remain open on the background");
      const mark = await page.locator(".bs-login__brand-mark").boundingBox();
      assert.ok(Math.abs(mark.x + mark.width / 2 - viewport.width / 2) < 1, "Brand mark must stay centered");
      if (reducedMotion === "no-preference") await page.locator(".bs-login-paper-bg canvas").waitFor({ state: "visible" });
      else assert.equal(await page.locator(".bs-login-paper-bg canvas").count(), 0);
      const screenshotSuffix = `${viewport.width}${reducedMotion === "no-preference" ? "-animated" : ""}`;
      if (process.env.MAVERICK_ACCOUNT_PANEL_SCREENSHOTS) await page.screenshot({ path: `/tmp/maverick-login-${screenshotSuffix}.png`, fullPage: true });
      // Verify the animated shader, then keep software rendering out of interaction timings.
      if (reducedMotion === "no-preference") {
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.locator(".bs-login-paper-bg canvas").waitFor({ state: "hidden" });
      }
      await google.click();
      await page.getByRole("button", { name: "Cancel Google sign-in", exact: true }).waitFor();
      assert.deepEqual(start, { mode: "login", services: ["calendar", "gmail", "drive"], transport: "system-browser" });
      await page.getByRole("button", { name: "Cancel Google sign-in", exact: true }).click();
      assert.equal(await google.isEnabled(), true);
      await page.waitForFunction(() => !document.querySelector(".bs-login__pending"));
      assert.equal(cancelled, 1);
      const serverLauncher = page.getByRole("button", { name: /^Change server / });
      assert.equal(await page.locator(".bs-server-launcher").count(), 0);
      assert.ok((await serverLauncher.boundingBox()).y >= googleBox.y + googleBox.height, "Change server belongs below the login options");
      await serverLauncher.click();
      const panel = page.getByRole("dialog", { name: "Servers", exact: true });
      await panel.getByRole("heading", { name: "Saved connections" }).waitFor();
      assert.equal(await panel.getByRole("heading", { name: "Servers", exact: true }).evaluate(element => element === document.activeElement), true);
      const box = await panel.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= viewport.width);
      assert.ok(box.y >= 0 && box.y + box.height <= viewport.height);
      if (viewport.width > 680) assert.ok(box.height < 800, "Server dialog should fit its content");
      assert.equal(await panel.evaluate(element => element.scrollWidth > element.clientWidth), false);
      await panel.getByLabel("Name", { exact: true }).fill("Offline test server");
      await panel.getByLabel("Server address", { exact: true }).fill("http://offline.example");
      await panel.getByRole("button", { name: "Add server", exact: true }).click();
      await panel.getByRole("alert").filter({ hasText: "HTTPS" }).waitFor();
      if (process.env.MAVERICK_ACCOUNT_PANEL_SCREENSHOTS) await page.screenshot({ path: `/tmp/maverick-servers-${viewport.width}.png` });
      await page.keyboard.press("Escape");
      await panel.waitFor({ state: "hidden" });
      await page.waitForFunction(() => document.activeElement?.matches(".bs-login__server"));
      // Password login remains available, with keyboard focus moving to the password.
      await page.getByLabel("Email or username", { exact: true }).fill("admin");
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      assert.equal(await page.getByLabel("Password", { exact: true }).evaluate(element => element === document.activeElement), true);
      await page.getByLabel("Password", { exact: true }).fill("fixture-password");
      await page.getByRole("button", { name: "Show password", exact: true }).click();
      assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("type"), "text");
      await page.getByRole("button", { name: "Hide password", exact: true }).click();
      assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("type"), "password");
      if (process.env.MAVERICK_ACCOUNT_PANEL_SCREENSHOTS) await page.screenshot({ path: `/tmp/maverick-login-password-${screenshotSuffix}.png`, fullPage: true });
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await page.getByRole("alert").filter({ hasText: "Invalid credentials" }).waitFor();
      assert.deepEqual(passwordLogin, { username: "admin", password: "fixture-password" });
      assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("aria-invalid"), "true");
      await page.getByRole("button", { name: "Back", exact: true }).click();
      assert.equal(await page.getByLabel("Email or username", { exact: true }).inputValue(), "admin");
      await google.waitFor({ state: "visible" });
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser?.close(); await close(server); }
});
