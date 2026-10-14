import assert from "node:assert/strict";
import { test } from "node:test";
import { chromium } from "./shell-presentation-fixture.mjs";
import { browserExecutable, close, listen } from "./browser-contract-support.mjs";
import { widgetLifecycleFixture } from "./widget-lifecycle-fixture.mjs";

async function frameFor(page, selector) {
  const element = page.locator(selector);
  await element.waitFor({ state: "attached" });
  const frame = await (await element.elementHandle()).contentFrame();
  await frame.locator("textarea").waitFor({ state: "attached" });
  return frame;
}

async function saveDraft(frame, value) {
  await frame.getByRole("textbox", { name: "Draft" }).fill(value);
  await frame.locator("#transcript").evaluate((element) => { element.scrollTop = 200; });
  return frame.evaluate(() => window.instance);
}

async function assertPreserved(frame, instance, draft) {
  assert.equal(await frame.evaluate(() => window.instance), instance);
  assert.equal(await frame.locator("textarea").inputValue(), draft);
  assert.equal(await frame.locator("#transcript").evaluate((element) => element.scrollTop), 200);
}

async function openApp(page, appId, mobile = false) {
  if (mobile) {
    await page.getByRole("button", { name: "Apri applicazioni pinnate", exact: true }).click();
    await page.getByRole("button", { name: appId, exact: true }).click();
  } else {
    // Exercise navigation independently of the rail's long-press reorder gesture.
    const shortcut = page.getByRole("button", { name: `${appId}. Alt+ArrowUp or Alt+ArrowDown to reorder.`, exact: true });
    await shortcut.focus();
    await shortcut.press("Enter");
  }
  await page.waitForURL((url) => url.pathname === `/app/${appId}`);
  await page.locator(`.bs-sidebar__persistent-widget[data-active="true"] iframe[title="App sidebar footer"]`)
    .waitFor({ state: "attached" });
}

test("warm sidebar, overlay and dock documents survive desktop app and placement navigation", { timeout: 90_000 }, async () => {
  const fixture = widgetLifecycleFixture();
  const origin = await listen(fixture.server);
  const browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined, args: ["--no-sandbox"] });
  let page;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("maverick:base-shell:session", JSON.stringify({ sidebarMode: "fixed" })));
    page = await context.newPage();
    page.setDefaultTimeout(10_000);
    await page.goto(`${origin}/app/chat`);
    await page.locator(".bs-sidebar__rail").hover();
    const footer = await frameFor(page, 'iframe[title="App sidebar footer"]');
    const footerInstance = await saveDraft(footer, "footer state");
    const primary = await frameFor(page, 'iframe[title="App sidebar content"]');
    const primaryInstance = await saveDraft(primary, "sidebar state");
    await page.getByRole("button", { name: "Sidebar fissa", exact: true }).click();
    await openApp(page, "storage");
    const overlay = await frameFor(page, 'iframe[title="Floating chat widget"]');
    const overlayInstance = await saveDraft(overlay, "overlay draft");
    await openApp(page, "calendar");
    await openApp(page, "chat");
    await assertPreserved(footer, footerInstance, "footer state");
    await assertPreserved(primary, primaryInstance, "sidebar state");
    await page.waitForFunction(() => document.querySelector(".bs-floating-chat-host")?.getAttribute("aria-hidden") === "true");
    assert.equal(await overlay.evaluate(() => window.visible), false);
    await openApp(page, "storage");
    await assertPreserved(overlay, overlayInstance, "overlay draft");
    await overlay.getByRole("button", { name: "Dock chat", exact: true }).click();
    const dock = await frameFor(page, 'iframe[title="Right dock widget"]');
    await assertPreserved(dock, overlayInstance, "overlay draft");
    const dockInstance = await saveDraft(dock, "dock draft");
    await openApp(page, "chat");
    await openApp(page, "storage");
    await assertPreserved(dock, dockInstance, "dock draft");
    await dock.getByRole("button", { name: "Return to overlay", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-placement="overlay"]')?.hidden === false);
    await assertPreserved(overlay, overlayInstance, "dock draft");
    const warmLaunches = fixture.launches.length;
    await openApp(page, "calendar");
    await openApp(page, "chat");
    await openApp(page, "storage");
    assert.equal(fixture.launches.length, warmLaunches, "warm navigation must not request new launch tickets");
    for (const widgetId of ["chat-sidebar", "chat-sidebar-footer", "chat-floating"]) {
      assert.equal(fixture.documents.filter((path) => path.includes(`/${widgetId}/`)).length, 1, widgetId);
    }
    await context.close();
  } catch (error) {
    console.error("Widget lifecycle failure:", page?.url(), await page?.locator(".bs-shell").getAttribute("class"), fixture.documents);
    throw error;
  } finally { await browser.close(); await close(fixture.server); }
});

test("mobile footer and contextual Chat preserve documents through closing and app navigation", { timeout: 45_000 }, async () => {
  const fixture = widgetLifecycleFixture();
  const origin = await listen(fixture.server);
  const browser = await chromium.launch({ headless: true, executablePath: browserExecutable() || undefined, args: ["--no-sandbox"] });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: "block" });
    const page = await context.newPage();
    await page.goto(`${origin}/app/chat`);
    await page.getByRole("button", { name: "Apri sidebar", exact: true }).click();
    const footer = await frameFor(page, 'iframe[title="App sidebar footer"]');
    const footerInstance = await saveDraft(footer, "mobile footer");
    await page.getByRole("button", { name: "Chiudi sidebar", exact: true }).click();
    await openApp(page, "storage", true);
    await page.getByRole("button", { name: "Apri chat contestuale", exact: true }).click();
    const chat = await frameFor(page, 'iframe[title="Mobile chat widget"]');
    const chatInstance = await saveDraft(chat, "mobile draft");
    assert.equal(await page.locator(".bs-workspace-view-shell").getAttribute("inert"), "");
    await page.getByRole("button", { name: "Chiudi chat contestuale", exact: true }).click();
    await page.waitForFunction(() => document.querySelector(".bs-floating-chat-host")?.getAttribute("aria-hidden") === "true");
    assert.equal(await chat.evaluate(() => window.visible), false);
    await openApp(page, "chat", true);
    await page.getByRole("button", { name: "Apri sidebar", exact: true }).click();
    await assertPreserved(footer, footerInstance, "mobile footer");
    assert.equal(await page.getByRole("button", { name: "New chat", exact: true }).isEnabled(), true);
    await page.getByRole("button", { name: "Chiudi sidebar", exact: true }).click();
    await openApp(page, "storage", true);
    await page.getByRole("button", { name: "Apri chat contestuale", exact: true }).click();
    await assertPreserved(chat, chatInstance, "mobile draft");
    await page.getByRole("button", { name: "Chiudi chat contestuale", exact: true }).focus();
    for (let step = 0; step < 8; step++) {
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.querySelector(".bs-workspace-view-shell")?.contains(document.activeElement)), false);
    }
    await page.getByRole("button", { name: "Chiudi chat contestuale", exact: true }).click();
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "Apri chat contestuale");
    await page.getByRole("button", { name: "Apri chat contestuale", exact: true }).click();
    await assertPreserved(chat, chatInstance, "mobile draft");
    await page.screenshot({ path: "/tmp/maverick-contextual-shell-mobile.png" });
    assert.equal(fixture.documents.filter((path) => path.includes("/chat-floating/")).length, 1);
    assert.equal(fixture.documents.filter((path) => path.includes("/chat-sidebar-footer/")).length, 1);
    await context.close();
  } finally { await browser.close(); await close(fixture.server); }
});
