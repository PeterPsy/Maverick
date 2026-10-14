import assert from "node:assert/strict";
import { test } from "node:test";
import { browserExecutable, close, listen } from "./browser-contract-support.mjs";
import { chromium, fixtureServer } from "./shell-presentation-fixture.mjs";

test("account panel supports desktop, mobile, keyboard and separated Google/logout actions", { timeout: 45_000 }, async () => {
  const server = fixtureServer([]);
  const origin = await listen(server);
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined, args: ["--no-sandbox"] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 950 }, serviceWorkers: "block" });
    await context.route("**/api/connected-accounts", route => route.fulfill({ json: {
      workspace_id: "default", items: [
        { account_id: "primary", email: "primary@example.com", display_name: "Primary Google", status: "connected", services: ["gmail"] },
        { account_id: "secondary", email: "secondary@example.com", display_name: "Secondary Google", status: "connected", services: ["calendar"] },
      ], selection: { account_id: "primary", account_ids: ["primary", "secondary"], disabled_apps: [] },
      apps: [{ app_id: "calendar", name: "Calendar", services: ["calendar"] }], google: { configured: true, services: [], registration_enabled: true, login_services: [] },
    } }));
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(`${origin}/app/chat`);
    await page.locator(".bs-sidebar__rail").hover();
    await page.getByRole("button", { name: "Account and servers", exact: true }).click();
    const panel = page.getByRole("dialog", { name: "Account and servers" });
    await panel.waitFor({ state: "visible" });
    const box = await panel.boundingBox();
    assert.ok(box.width >= 900 && box.width <= 960);
    assert.ok(box.y >= 0 && box.y + box.height <= 950);
    assert.equal(await panel.getByRole("heading", { name: "Your profile" }).count(), 1);
    assert.ok((await panel.textContent()).includes("fixture"));
    await panel.getByRole("button", { name: "Connected accounts", exact: true }).click();
    await panel.getByText("secondary@example.com", { exact: true }).waitFor();
    await panel.getByRole("button", { name: "Disconnect", exact: true }).first().click();
    assert.ok((await panel.textContent()).includes("in all workspaces"));
    assert.equal(await panel.getByRole("button", { name: "Log out of this server", exact: true }).count(), 0);
    await panel.getByRole("button", { name: "App access", exact: true }).click();
    assert.equal(await panel.getByRole("checkbox", { name: "Use secondary@example.com in this workspace" }).isChecked(), true);
    assert.equal(await panel.getByRole("checkbox", { name: "Allow Calendar to use Google" }).isChecked(), true);
    if (process.env.LOOPINO_ACCOUNT_PANEL_SCREENSHOTS) await page.screenshot({ path: "/tmp/loopino-account-panel-desktop.png" });
    await panel.getByRole("button", { name: "Servers", exact: true }).click();
    await panel.getByLabel("Name", { exact: true }).fill("GiuntiTrail");
    await panel.getByLabel("Server address", { exact: true }).fill("http://trail.example");
    await panel.getByRole("button", { name: "Add server", exact: true }).click();
    await panel.getByRole("alert").filter({ hasText: "HTTPS" }).waitFor();
    await panel.getByLabel("Server address", { exact: true }).fill("https://trail.example");
    await panel.getByRole("button", { name: "Add server", exact: true }).click();
    await panel.getByText("GiuntiTrail", { exact: true }).waitFor();
    await panel.getByRole("button", { name: "Log out", exact: true }).click();
    assert.ok((await panel.textContent()).includes("other servers stay available"));
    await page.keyboard.press("Escape");
    await panel.waitFor({ state: "hidden" });
    assert.equal(await page.getByRole("button", { name: "Account and servers", exact: true }).evaluate(element => element === document.activeElement), true);

    // A fresh mobile session also mounts the account entry and fits short viewports.
    await context.close();
    const mobile = await browser.newContext({ viewport: { width: 390, height: 650 }, isMobile: true, hasTouch: true, serviceWorkers: "block" });
    await mobile.route("**/api/connected-accounts", route => route.fulfill({ json: {
      workspace_id: "default", items: [{ account_id: "long-address", email: "very.long.account.address.for.mobile@example.com", display_name: "Personal Google account", status: "connected", services: ["gmail"] }],
      selection: null, apps: [], google: { configured: true, services: [], registration_enabled: true, login_services: [] },
    } }));
    const phone = await mobile.newPage();
    await phone.goto(`${origin}/app/chat`);
    await phone.getByRole("button", { name: "Apri sidebar", exact: true }).click();
    await phone.getByRole("button", { name: "Account and servers", exact: true }).click();
    const mobilePanel = phone.getByRole("dialog", { name: "Account and servers" });
    await mobilePanel.waitFor({ state: "visible" });
    await phone.addStyleTag({ content: ".bs-shell { --bs-mobile-shell-status-bar-height: 47px; }" });
    const mobileBox = await mobilePanel.boundingBox();
    assert.ok(mobileBox.x >= 0 && mobileBox.x + mobileBox.width <= 390);
    assert.ok(mobileBox.y >= 59 && mobileBox.y + mobileBox.height <= 638);
    const sectionPicker = mobilePanel.getByRole("combobox", { name: "Account section" });
    assert.equal(await sectionPicker.locator("option").count(), 6);
    const pickerBox = await sectionPicker.boundingBox();
    assert.ok(pickerBox.height >= 44 && pickerBox.x + pickerBox.width <= 390);
    if (process.env.LOOPINO_ACCOUNT_PANEL_SCREENSHOTS) await phone.screenshot({ path: "/tmp/loopino-account-panel-profile-mobile.png" });
    await sectionPicker.selectOption("servers");
    const overflow = await mobilePanel.evaluate(element => element.scrollWidth > element.clientWidth);
    assert.equal(overflow, false);
    if (process.env.LOOPINO_ACCOUNT_PANEL_SCREENSHOTS) {
      await phone.screenshot({ path: "/tmp/loopino-account-panel-mobile.png" });
    }
    await phone.setViewportSize({ width: 320, height: 568 });
    for (const section of ["profile", "google", "access", "servers", "logout"]) {
      await sectionPicker.selectOption(section);
      assert.equal(await mobilePanel.evaluate(element => Array.from(element.querySelectorAll(".bs-connected-accounts__body, .bs-connected-accounts__account")).some(node => node.scrollWidth > node.clientWidth)), false);
      const closeBox = await mobilePanel.getByRole("button", { name: "Close account panel" }).boundingBox();
      assert.ok(closeBox.y >= 59 && closeBox.x + closeBox.width <= 320);
      if (process.env.LOOPINO_ACCOUNT_PANEL_SCREENSHOTS && section === "google") await phone.screenshot({ path: "/tmp/loopino-account-panel-accounts-narrow.png" });
    }
    assert.deepEqual(errors, []);
    await mobile.close();
  } finally {
    await browser?.close();
    await close(server);
  }
});
