import assert from "node:assert/strict";
import { resolve } from "node:path";
import { test } from "node:test";
import { browserExecutable, close, listen } from "./browser-contract-support.mjs";
import { appRoot, chromium, fixtureServer } from "./shell-presentation-fixture.mjs";

test("built shell supports app sidebar opt-out, desktop menus, saved preferences and mobile touch", { timeout: 45_000 }, async () => {
  const requests = [];
  const server = fixtureServer(requests);
  const origin = await listen(server);
  let browser;
  let lastPage;
  try {
    // Render backdrop blur with a software GPU on headless hosts.
    browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined,
      args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
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
    const railPadding = await rail.evaluate((element) => {
      const style = getComputedStyle(element);
      return [parseFloat(style.paddingTop), parseFloat(style.paddingBottom)];
    });
    assert.ok(railPadding.every((padding) => padding >= 12));
    assert.equal(await rail.locator(".bs-sidebar__rail-background-dot").count(), 0);
    assert.equal(await page.locator(".bs-sidebar.is-open").count(), 0);
    assert.equal(await page.locator(".bs-sidebar__resize-handle").count(), 0);
    assert.ok((await page.locator(".bs-workspace-view-shell").boundingBox()).x < 100);
    assert.ok(!requests.some((url) => /content_kind=shell.sidebar.(primary|footer)/.test(url)));

    const top = page.getByRole("button", { name: "Controlli workspace", exact: true });
    await top.hover();
    for (const trigger of await page.locator(".bs-sidebar__rail-menu-trigger").all()) {
      assert.deepEqual(await trigger.evaluate((button) => {
        const style = getComputedStyle(button);
        return [style.backgroundColor, style.color];
      }), ["rgb(255, 255, 255)", "rgb(10, 10, 11)"]);
    }
    const workspace = page.getByRole("combobox", { name: "Workspace", exact: true });
    await workspace.waitFor({ state: "visible" });
    await workspace.hover();
    assert.equal(await top.getAttribute("aria-expanded"), "true");
    const panel = await page.locator(".bs-sidebar__rail-menu-panel").boundingBox();
    assert.ok(panel.x > (await rail.boundingBox()).x);
    assert.ok(panel.x + panel.width <= 1440);
    const bell = page.getByRole("button", { name: "Notifiche (1)", exact: true });
    const gear = page.getByRole("button", { name: "Impostazioni di canvas", exact: true });
    const bellBox = await bell.boundingBox();
    const gearBox = await gear.boundingBox();
    assert.ok(bellBox.x > gearBox.x + gearBox.width);
    assert.equal(bellBox.width, gearBox.width);
    assert.equal(bellBox.height, gearBox.height);
    assert.deepEqual(await bell.evaluate((button) => {
      const style = getComputedStyle(button);
      const icon = getComputedStyle(button.querySelector(".material-symbols-rounded"));
      return [style.borderRadius, style.backgroundColor, style.borderColor, icon.fontSize, icon.fontVariationSettings];
    }), await gear.evaluate((button) => {
      const style = getComputedStyle(button);
      const icon = getComputedStyle(button.querySelector(".material-symbols-rounded"));
      return [style.borderRadius, style.backgroundColor, style.borderColor, icon.fontSize, icon.fontVariationSettings];
    }));
    await bell.click();
    const inbox = page.getByRole("region", { name: "Notifiche da leggere" });
    await inbox.waitFor({ state: "visible" });
    assert.equal(await inbox.evaluate((element) => element.matches(":popover-open")), true);
    assert.equal(await page.getByRole("button", { name: "Promemoria di prova", exact: true })
      .evaluate((button) => button === document.activeElement), true);
    await page.keyboard.press("Tab");
    assert.equal(await page.getByRole("button", { name: "Chiudi notifica: Promemoria di prova", exact: true })
      .evaluate((button) => button === document.activeElement), true);
    await page.keyboard.press("Escape");
    await inbox.waitFor({ state: "hidden" });
    assert.equal(await bell.evaluate((button) => button === document.activeElement), true);
    assert.equal(await top.getAttribute("aria-expanded"), "true");
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, "sidebar-desktop.png") });
    await top.focus();
    await page.keyboard.press("Escape");
    assert.equal(await top.getAttribute("aria-expanded"), "false");

    await page.getByRole("button", { name: "Controlli Maverick", exact: true }).hover();
    assert.equal(await page.getByRole("button", { name: "Sidebar fissa", exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "Solo app in overlay", exact: true }).count(), 0);
    const bottomPanel = page.locator(".bs-sidebar__rail-menu--bottom .bs-sidebar__rail-menu-panel");
    assert.deepEqual(await bottomPanel.evaluate((element) => {
      const style = getComputedStyle(element);
      const railStyle = getComputedStyle(document.querySelector(".bs-sidebar__rail"));
      return [style.backdropFilter, style.backgroundColor, railStyle.backdropFilter];
    }), ["blur(26px)", "rgba(12, 12, 14, 0.58)", "none"]);
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, "sidebar-bottom-dark.png") });
    await page.getByRole("button", { name: "Light mode", exact: true }).click();
    assert.equal(await page.locator("html").getAttribute("data-maverick-theme"), "light");
    await page.waitForFunction(() => [...document.querySelectorAll(".bs-sidebar__rail-menu-trigger")].every((button) => {
      const style = getComputedStyle(button);
      return style.backgroundColor === "rgb(17, 24, 39)" && style.color === "rgb(255, 255, 255)";
    }));
    for (const trigger of await page.locator(".bs-sidebar__rail-menu-trigger").all()) {
      assert.deepEqual(await trigger.evaluate((button) => {
        const style = getComputedStyle(button);
        return [style.backgroundColor, style.color];
      }), ["rgb(17, 24, 39)", "rgb(255, 255, 255)"]);
    }
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, "sidebar-bottom-light.png") });
    await page.getByRole("button", { name: "chat. Alt+ArrowUp or Alt+ArrowDown to reorder.", exact: true }).click();
    await page.locator(".bs-shell.is-sidebar-mode-fixed").waitFor();
    const canvasButton = page.getByRole("button", { name: "canvas. Alt+ArrowUp or Alt+ArrowDown to reorder.", exact: true });
    const canvasDot = canvasButton.locator(".bs-sidebar__rail-background-dot");
    await canvasDot.waitFor({ state: "visible" });
    assert.equal(await canvasButton.getAttribute("aria-description"), "Open in background");
    const dotBox = await canvasDot.boundingBox();
    const canvasBox = await canvasButton.boundingBox();
    const railBox = await rail.boundingBox();
    assert.ok(dotBox.x >= railBox.x && dotBox.x + dotBox.width < canvasBox.x);
    assert.ok(Math.abs(dotBox.y + dotBox.height / 2 - canvasBox.y - canvasBox.height / 2) < 1);
    assert.equal(await rail.locator(".bs-sidebar__rail-button.is-active .bs-sidebar__rail-background-dot").count(), 0);
    if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, "sidebar-background-light.png") });
    assert.equal(await page.getByRole("button", { name: "Sidebar fissa", exact: true }).getAttribute("aria-pressed"), "true");
    assert.equal(await page.getByRole("button", { name: "Solo app in overlay", exact: true }).count(), 1);
    await page.waitForFunction(() => document.querySelector(".bs-workspace-view-shell").getBoundingClientRect().x > 300);
    assert.equal(await page.locator(".bs-sidebar__header > .bs-notifications").count(), 1);
    await bell.click();
    await inbox.waitFor({ state: "visible" });
    await page.getByRole("button", { name: "Promemoria di prova", exact: true }).hover();
    const fixedInboxBox = await inbox.boundingBox();
    assert.ok(fixedInboxBox.x >= 0 && fixedInboxBox.x + fixedInboxBox.width <= 1440);
    await page.mouse.click(1400, 800);
    await inbox.waitFor({ state: "hidden" });
    await page.waitForFunction(() => document.querySelector(".bs-notifications__toggle")?.getAttribute("aria-expanded") === "false");
    await page.getByRole("button", { name: "canvas. Alt+ArrowUp or Alt+ArrowDown to reorder.", exact: true }).click();
    await page.locator(".bs-sidebar--disabled").waitFor();
    await page.waitForFunction(() => document.querySelector('.bs-sidebar__rail-button[aria-current="page"] .bs-sidebar__rail-background-dot') === null);
    assert.equal(await rail.locator(".bs-sidebar__rail-background-dot").count(), 1);
    await page.waitForFunction(() => document.querySelector(".bs-workspace-view-shell").getBoundingClientRect().x < 100);
    await context.close();

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: "block" });
    const mobilePage = await mobile.newPage();
    lastPage = mobilePage;
    await mobilePage.goto(`${origin}/app/canvas`);
    const mobileBell = mobilePage.getByRole("button", { name: "Notifiche (1)", exact: true });
    await mobileBell.waitFor();
    for (const width of [390, 320]) {
      await mobilePage.setViewportSize({ width, height: 844 });
      assert.equal(await mobilePage.locator(".bs-notifications__toggle").count(), 1);
      assert.equal(await mobilePage.locator(".bs-mobile-shell-header__actions > :last-child .bs-notifications__toggle").count(), 1);
      const plus = mobilePage.locator(".bs-mobile-shell-header__primary-action");
      const plusBox = await plus.boundingBox();
      const mobileBellBox = await mobileBell.boundingBox();
      const logoBox = await mobilePage.locator(".bs-mobile-shell-header__logo-button").boundingBox();
      const actionsBox = await mobilePage.locator(".bs-mobile-shell-header__actions").boundingBox();
      assert.ok(mobileBellBox.x >= plusBox.x + plusBox.width);
      assert.ok(mobileBellBox.x + mobileBellBox.width <= width);
      assert.ok(logoBox.x + logoBox.width <= actionsBox.x);
      assert.equal(await mobileBell.evaluate((button) => getComputedStyle(button).height),
        await plus.evaluate((button) => getComputedStyle(button).height));
      await mobileBell.tap();
      const mobileInbox = mobilePage.getByRole("region", { name: "Notifiche da leggere" });
      await mobileInbox.waitFor({ state: "visible" });
      const inboxBox = await mobileInbox.boundingBox();
      assert.ok(inboxBox.x >= 0 && inboxBox.x + inboxBox.width <= width);
      assert.ok(inboxBox.y >= mobileBellBox.y + mobileBellBox.height);
      await mobilePage.keyboard.press("Escape");
      await mobileInbox.waitFor({ state: "hidden" });
    }
    await mobilePage.setViewportSize({ width: 390, height: 844 });
    await mobilePage.getByRole("button", { name: "Apri controlli workspace", exact: true }).tap();
    await mobilePage.getByRole("combobox", { name: "Workspace", exact: true }).waitFor({ state: "visible" });
    assert.equal(await mobilePage.getByRole("button", { name: "Sidebar fissa", exact: true }).count(), 0);
    assert.equal(await mobilePage.getByRole("button", { name: "Solo app in overlay", exact: true }).count(), 0);
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
