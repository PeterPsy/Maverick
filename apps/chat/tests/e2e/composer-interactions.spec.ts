import { expect, test, type Locator, type Page } from "@playwright/test";

for (const width of [390, 900]) {
  test(`Research uploads images and files at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width: width + 40, height: 844 });
    const composer = await openFixture(page, width, false, 1, true);
    const chooserPromise = page.waitForEvent("filechooser");
    await composer.getByRole("button", { name: "Add attachments" }).click();
    const chooser = await chooserPromise;
    await chooser.setFiles([
      { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("Research evidence") },
      { name: "scan.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8K0AAAAASUVORK5CYII=", "base64") },
    ]);
    await expect(composer.getByLabel("Selected attachments")).toContainText("notes.txt");
    await expect(composer.getByLabel("Selected attachments")).toContainText("scan.png");
    await expect(composer.locator(".chatapp-attachment-card.is-invalid")).toHaveCount(0);
    await expect(composer.locator(".chatapp-attachment-card__preview")).toBeVisible();
    await composer.getByRole("button", { name: "Remove notes.txt" }).click();
    await expect(composer.locator(".chatapp-attachment-card")).toHaveCount(1);
    await expect(composer.getByRole("button", { name: "Apps and references" })).toHaveCount(0);
  });
}

async function openFixture(page: Page, width = 390, widget = false, count = 1, research = false, usage = false) {
  await page.route("**/material-symbols-rounded.woff2", (route) => route.fulfill({
    path: "../base-shell/frontend/public/material-symbols-rounded.woff2", contentType: "font/woff2",
  }));
  await page.goto(`/apps/chat/tests/composer/index.html?width=${width}&widget=${widget}&count=${count}&research=${research}${usage ? "&usage=true" : ""}`);
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
      await expect(composer.getByRole("button", { name: "Stop chat" })).toBeVisible();
      await expect(composer.getByRole("button", { name: "Send message" })).toHaveCount(0);
      await composer.getByRole("textbox").fill("A saved draft");
      await expect(composer.getByRole("button", { name: "Stop chat" })).toHaveCount(0);
      await page.getByTestId("outside").click();
      const utility = composer.getByRole("button", { name: "Composer utilities" });
      await activate(page, utility, touch);
      await activate(page, composer.getByRole("button", { name: "Send message" }), touch);
      await expect(page.getByTestId("sent")).toHaveText("1");
      await expect(composer.getByRole("textbox")).toHaveText("");
      await expect(composer.getByRole("button", { name: "Send message" })).toHaveCount(0);
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

    test("returns from utility pickers and closes the panel with focus restored", async ({ page }) => {
      const composer = await openFixture(page, width, widget);
      const utility = composer.getByRole("button", { name: "Composer utilities" });
      await activate(page, utility, touch);
      for (const name of ["Agent runner: Free Agent", "Model: Codex", "Multi-agent mode: Off"]) {
        const trigger = composer.getByRole("button", { name });
        await activate(page, trigger, touch);
        await activate(page, composer.getByRole("button", { name: "Back to utilities" }), touch);
        await expect(trigger).toBeVisible();
        await expect(trigger).toBeFocused();
        await expect(utility).toHaveAttribute("aria-expanded", "true");
      }
      await activate(page, composer.getByRole("button", { name: "Multi-agent mode: Off" }), touch);
      await composer.getByRole("button", { name: "Close utilities" }).focus();
      await page.keyboard.press("Escape");
      await expect(composer.getByRole("button", { name: "Multi-agent mode: Off" })).toBeFocused();
      await activate(page, composer.getByRole("button", { name: "Model: Codex" }), touch);
      await activate(page, composer.getByRole("button", { name: "Close utilities" }), touch);
      await expect(utility).toHaveAttribute("aria-expanded", "false");
      await expect(utility).toBeFocused();
      await activate(page, utility, touch);
      await expect(composer.getByRole("button", { name: "Model: Codex" })).toBeVisible();
      await expect(composer.getByRole("listbox")).toHaveCount(0);
    });
  });
}

for (const theme of ["dark", "light"]) {
  test(`utility rows stay readable and within a narrow ${theme} viewport`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    const composer = await openFixture(page, 320);
    await page.evaluate((value) => { document.documentElement.dataset.maverickTheme = value; }, theme);
    await composer.getByRole("button", { name: "Composer utilities" }).click();
    const panel = composer.getByRole("group", { name: "Composer utility controls" });
    const bounds = (await panel.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.y).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(320);
    for (const name of ["Apps and references", "Multi-agent mode: Off", "Agent runner: Free Agent", "Model: Codex"]) {
      const row = panel.getByRole("button", { name });
      await row.scrollIntoViewIfNeeded();
      const rowBounds = (await row.boundingBox())!;
      expect(rowBounds.height).toBeGreaterThanOrEqual(44);
      expect(rowBounds.width).toBeGreaterThan(bounds.width - 40);
      await expect(row.locator(".chatapp-composer-utilities__copy")).toBeVisible();
    }
    await expect(panel.getByRole("button", { name: "Close utilities" })).toBeInViewport();
    if (process.env.MAVERICK_CHAT_PANEL_SCREENSHOTS) await page.screenshot({ path: `/tmp/maverick-chat-utilities-${theme}.png` });
  });
}

async function installMobileShellChrome(page: Page) {
  await page.evaluate(() => {
    document.documentElement.style.setProperty("--maverick-shell-mobile-content-top-offset", "91px");
    const header = document.createElement("header");
    header.dataset.testid = "shell-chrome";
    header.setAttribute("aria-hidden", "true");
    header.textContent = "☰  Maverick                       +";
    Object.assign(header.style, {
      position: "fixed", top: "47px", left: "0", right: "0", height: "44px",
      zIndex: "1001", display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--maverick-bg)", color: "var(--maverick-text)",
    });
    document.body.appendChild(header);
  });
  await page.addStyleTag({ content: ".chatapp-usage-modal-backdrop { --chatapp-usage-bottom-clearance: 34px; }" });
}

for (const width of [320, 390, 1280]) {
  for (const theme of ["dark", "light"]) {
    test(`token usage fits ${width}px in ${theme} mode and returns to its trigger`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      const composer = await openFixture(page, width, false, 1, false, true);
      await page.evaluate((value) => { document.documentElement.dataset.maverickTheme = value; }, theme);
      if (width <= 979) await installMobileShellChrome(page);
      const utilities = composer.getByRole("button", { name: "Composer utilities" });
      if (width <= 720) await utilities.click();
      const usage = composer.getByRole("button", { name: /Chat token usage/ });
      await usage.click();
      const dialog = page.getByRole("dialog", { name: "Token usage" });
      const close = dialog.getByRole("button", { name: "Close token usage statistics" });
      await expect(close).toBeFocused();
      await expect(dialog.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "45");
      const bounds = (await dialog.boundingBox())!;
      expect(bounds.x).toBeGreaterThanOrEqual(0);
      expect(bounds.y).toBeGreaterThanOrEqual(0);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(700);
      if (width <= 979) {
        expect(bounds.y).toBeGreaterThanOrEqual(103);
        expect(bounds.y + bounds.height).toBeLessThanOrEqual(654);
        const closeBounds = (await close.boundingBox())!;
        expect(closeBounds.width).toBeGreaterThanOrEqual(44);
        expect(closeBounds.height).toBeGreaterThanOrEqual(44);
      }
      expect(await dialog.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(false);
      await dialog.locator(".chatapp-usage-modal__note").scrollIntoViewIfNeeded();
      await expect(close).toBeInViewport();
      if (width <= 979) expect((await close.boundingBox())!.y).toBeGreaterThanOrEqual(103);
      await page.keyboard.press("Tab");
      await expect(close).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      await expect(close).toBeFocused();
      if (process.env.MAVERICK_CHAT_PANEL_SCREENSHOTS && width !== 320) {
        await dialog.locator(".chatapp-usage-modal__context").scrollIntoViewIfNeeded();
        await page.screenshot({ path: `/tmp/maverick-chat-token-usage-${width}-${theme}.png` });
      }
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(usage).toBeFocused();
      if (width <= 720) await expect(utilities).toHaveAttribute("aria-expanded", "true");
      await usage.click();
      await close.click();
      await expect(usage).toBeFocused();
      await usage.click();
      await page.mouse.click(2, 2);
      await expect(dialog).toBeHidden();
      await expect(usage).toBeFocused();
    });
  }
}

test("token usage clears shell navigation in a short landscape viewport", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 480 });
  const composer = await openFixture(page, 900, false, 1, false, true);
  await installMobileShellChrome(page);
  await composer.getByRole("button", { name: /Chat token usage/ }).click();
  const dialog = page.getByRole("dialog", { name: "Token usage" });
  const bounds = (await dialog.boundingBox())!;
  expect(bounds.y).toBeGreaterThanOrEqual(103);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(434);
  await dialog.locator(".chatapp-usage-modal__note").scrollIntoViewIfNeeded();
  const close = dialog.getByRole("button", { name: "Close token usage statistics" });
  await expect(close).toBeInViewport();
  await close.click();
  await expect(dialog).toBeHidden();
});

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
