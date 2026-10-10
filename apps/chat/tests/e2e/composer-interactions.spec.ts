import { expect, test, type Locator, type Page } from "@playwright/test";

async function openFixture(page: Page, width = 390, widget = false, count = 1) {
  await page.route("**/material-symbols-rounded.woff2", (route) => route.fulfill({
    path: "../base-shell/frontend/public/material-symbols-rounded.woff2", contentType: "font/woff2",
  }));
  await page.goto(`/apps/chat/tests/composer/index.html?width=${width}&widget=${widget}&count=${count}`);
  const composer = page.locator(".chatapp-composer").first();
  await expect(composer.getByRole("textbox")).toBeEditable();
  await page.evaluate(() => document.fonts.ready);
  return composer;
}

async function editorHeight(composer: Locator) {
  return (await composer.getByRole("textbox").boundingBox())!.height;
}

async function activate(page: Page, button: Locator, touch: boolean) {
  if (touch) await button.tap();
  else {
    const box = (await button.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.up();
  }
}

for (const { label, width, touch, widget } of [
  { label: "mobile mouse", width: 390, touch: false, widget: false },
  { label: "mobile touch", width: 390, touch: true, widget: false },
  { label: "side chat", width: 480, touch: false, widget: true },
  { label: "floating in a wide frame", width: 390, touch: false, widget: true },
]) {
  test.describe(label, () => {
    test.use({ viewport: { width: widget ? 1000 : 390, height: 844 }, hasTouch: touch });

    test("opens attachments on the first click without expanding the editor", async ({ page }) => {
      const composer = await openFixture(page, width, widget);
      const initialHeight = await editorHeight(composer);
      const chooser = page.waitForEvent("filechooser");
      await activate(page, composer.getByRole("button", { name: "Add attachments" }), touch);
      await chooser;
      expect(await editorHeight(composer)).toBe(initialHeight);
      await composer.getByRole("textbox").fill("Keep my draft and focus");
      const expandedHeight = await editorHeight(composer);
      const focusedChooser = page.waitForEvent("filechooser");
      await activate(page, composer.getByRole("button", { name: "Add attachments" }), touch);
      await focusedChooser;
      await expect(composer.getByRole("textbox")).toBeFocused();
      expect(await editorHeight(composer)).toBe(expandedHeight);
    });

    test("keeps editor expansion independent of utility menus and their focus", async ({ page }) => {
      const composer = await openFixture(page, width, widget);
      const initialHeight = await editorHeight(composer);
      const utility = composer.getByRole("button", { name: "Composer utilities" });
      await activate(page, utility, touch);
      expect(await editorHeight(composer)).toBe(initialHeight);
      for (const [button, menu] of [["Agent runner: Free Agent", "Choose agent runner"], ["Model: Codex", "Choose model"]]) {
        const trigger = composer.getByRole("button", { name: button });
        await activate(page, trigger, touch);
        await expect(composer.getByRole("listbox", { name: menu })).toBeVisible();
        expect(await editorHeight(composer)).toBe(initialHeight);
        await page.keyboard.press("Escape");
        await expect(trigger).toBeFocused();
        await expect(utility).toHaveAttribute("aria-expanded", "true");
      }
      const multiAgent = composer.getByRole("button", { name: "Multi-agent mode: Off" });
      await activate(page, multiAgent, touch);
      await expect(composer.getByRole("menu")).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(multiAgent).toBeFocused();
      await expect(utility).toHaveAttribute("aria-expanded", "true");
      await page.keyboard.press("Escape");
      await composer.getByRole("textbox").focus();
      const expandedHeight = await editorHeight(composer);
      expect(expandedHeight).toBeGreaterThan(initialHeight);
      await activate(page, utility, touch);
      await activate(page, composer.getByRole("button", { name: "Agent runner: Free Agent" }), touch);
      await expect(composer.getByRole("searchbox", { name: "Search agents" })).toBeFocused();
      expect(await editorHeight(composer)).toBe(expandedHeight);
      await page.keyboard.press("Escape");
      expect(await editorHeight(composer)).toBe(expandedHeight);
      await page.getByTestId("outside").click();
      expect(await editorHeight(composer)).toBe(initialHeight);
    });

    test("sends and stops on the first click with utilities open and the editor unfocused", async ({ page }) => {
      const composer = await openFixture(page, width, widget);
      await composer.getByRole("textbox").fill("A saved draft");
      await page.getByTestId("outside").click();
      const utility = composer.getByRole("button", { name: "Composer utilities" });
      await activate(page, utility, touch);
      await activate(page, composer.getByRole("button", { name: "Send message" }), touch);
      await expect(page.getByTestId("sent")).toHaveText("1");
      await expect(composer.getByRole("textbox")).toHaveText("");
      await activate(page, utility, touch);
      await activate(page, composer.getByRole("button", { name: "Stop chat" }), touch);
      await expect(page.getByTestId("stopped")).toHaveText("1");
    });

    test("inserts app references without opening a collapsed editor", async ({ page }) => {
      const composer = await openFixture(page, width, widget);
      const initialHeight = await editorHeight(composer);
      await activate(page, composer.getByRole("button", { name: "Composer utilities" }), touch);
      const apps = composer.getByRole("button", { name: "Apps and references" });
      await activate(page, apps, touch);
      await composer.locator(".chatapp-mention-panel__item").first().click();
      await expect(composer.getByRole("textbox")).toContainText("Storage");
      expect(await editorHeight(composer)).toBe(initialHeight);
      await expect(apps).toBeFocused();
      await activate(page, apps, touch);
      await page.keyboard.press("Escape");
      await expect(apps).toBeFocused();
    });
  });
}

test("groups controls by each composer width and changes layout at the container boundary", async ({ page }) => {
  await page.setViewportSize({ width: 1700, height: 900 });
  await openFixture(page, 390, true, 2);
  for (const composer of await page.locator(".chatapp-composer").all()) {
    await expect(composer.getByRole("button", { name: "Composer utilities" })).toBeVisible();
  }
  const composer = await openFixture(page, 724);
  await expect(composer.getByRole("button", { name: "Composer utilities" })).toBeHidden();
  await composer.evaluate((element) => { element.style.width = "722px"; });
  await expect(composer.getByRole("button", { name: "Composer utilities" })).toBeVisible();
});
