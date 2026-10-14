import { expect, test } from "@playwright/test";
import { installActiveTurn, SESSION_ID, TURN_ID } from "./fixtures/activeTurn";

for (const { surface, width, touch, path, widgetMode } of [
  { surface: "app", width: 1280, touch: false, path: `/apps/chat/?thread_id=${SESSION_ID}` },
  { surface: "app", width: 390, touch: false, path: `/apps/chat/?thread_id=${SESSION_ID}` },
  { surface: "app", width: 390, touch: true, path: `/apps/chat/?thread_id=${SESSION_ID}` },
  {
    surface: "floating", width: 480, touch: false, widgetMode: "overlay",
    path: "/apps/chat/widgets/chat-floating/index.html?context=steering-fixture",
  },
  {
    surface: "dock", width: 480, touch: false, widgetMode: "fixed-right",
    path: "/apps/chat/widgets/chat-floating/index.html?context=steering-fixture",
  },
  {
    surface: "fullscreen", width: 390, touch: true, widgetMode: "mobile-fullscreen",
    path: "/apps/chat/widgets/chat-floating/index.html?context=steering-fixture",
  },
]) {
  test.describe(`${surface} active-turn steering at ${width}px with ${touch ? "touch" : "mouse"}`, () => {
    test.use({ viewport: { width, height: 844 }, hasTouch: touch });

    test("sends consecutive messages without waiting for completion", async ({ page }) => {
      const submissions = await installActiveTurn(page, widgetMode);
      await page.goto(path);
      await expect(page.getByText("I am still working.", { exact: true })).toBeVisible();
      const composer = page.getByRole("textbox");
      const send = page.getByRole("button", { name: "Send message" });

      for (const input of ["Check the rail first", "Then check project names"]) {
        await expect(composer).toBeEditable();
        await composer.focus();
        await composer.fill(input);
        if (submissions.length) {
          // Sending an existing draft must also work after leaving the editor.
          await page.getByText("I am still working.", { exact: true }).click();
          await expect(composer).not.toBeFocused();
        }
        await expect(send).toBeEnabled();
        if (touch) await send.tap();
        else await send.click();
        await expect.poll(() => submissions.at(-1)?.input_text).toBe(input);
        await expect(composer).toHaveText("");
        await expect(page.getByText(input, { exact: true })).toBeVisible();
      }

      await composer.focus();
      await composer.fill("Keyboard steering still works");
      await send.focus();
      await page.keyboard.press("Enter");
      await expect.poll(() => submissions.at(-1)?.input_text).toBe("Keyboard steering still works");
      await expect(composer).toHaveText("");
      await expect(page.getByText("Keyboard steering still works", { exact: true })).toBeVisible();

      expect(submissions).toHaveLength(3);
      for (const body of submissions) {
        expect(body).toMatchObject({ async: true, delivery_policy: "steer_or_queue", expected_runtime_turn_id: TURN_ID });
        expect(body.client_message_id).toEqual(expect.any(String));
      }
      expect(new Set(submissions.map((body) => body.client_message_id)).size).toBe(3);
    });
  });
}

test.describe("fixed dock compact utilities", () => {
  test.use({ viewport: { width: 480, height: 844 } });

  test("shows the same model and runtime controls as the mobile composer", async ({ page }) => {
    await installActiveTurn(page, "fixed-right");
    await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");

    const composer = page.locator(".chatapp-composer");
    await composer.getByRole("button", { name: "Composer utilities" }).click();

    await expect(composer.getByRole("button", { name: "Capture page area" })).toHaveCount(0);
    await expect(composer.getByRole("button", { name: "Model: Codex" })).toBeVisible();
    await expect(composer.getByRole("img", { name: "Sandbox runtime" })).toBeVisible();
  });
});

test("preserves the real composer, attachments and other drafts through every placement", async ({ page }) => {
  const submissions = await installActiveTurn(page, "overlay");
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  const composer = page.getByRole("textbox");
  await composer.fill("Unsent work survives docking");
  const activeSlot = page.locator(".chat-floating-window-slot").first();
  const windowId = await activeSlot.getAttribute("data-window-id");
  await page.locator(".chat-floating-widget-shell").first().evaluate((element) => {
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(new File(["Example attachment"], "draft.txt", { type: "text/plain" }));
    element.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }));
  });
  await expect(page.getByText("draft.txt", { exact: true }).first()).toBeVisible();
  const marker = await composer.evaluate((element) => {
    element.setAttribute("data-draft-instance", "original");
    return element.getAttribute("data-draft-instance");
  });
  for (const mode of ["fixed-right", "mobile-fullscreen", "overlay"]) {
    await page.evaluate(({ mode, windowId }) => window.postMessage({
      type: "maverick.widget.context-changed", owner_app_id: "chat", widget_id: "chat-floating",
      context: { content: { workspace_id: "default", payload: { mode, navigation_scope: windowId, thread_id: "stale-thread" } } },
    }, window.location.origin), { mode, windowId });
    await expect(page.locator(".chat-floating-widget-stack")).toHaveClass(new RegExp(`is-${mode}`));
    await expect(composer).toHaveText("Unsent work survives docking");
    await expect(composer).toHaveAttribute("data-draft-instance", marker!);
    await expect(page.getByText("draft.txt", { exact: true }).first()).toBeVisible();
  }
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await expect(page.locator(".chat-floating-window-slot")).toHaveCount(2);
  await activeSlot.getByRole("button", { name: "Dock chat to right" }).click();
  await page.evaluate(({ windowId, threadId }) => window.postMessage({
    type: "maverick.widget.context-changed", owner_app_id: "chat", widget_id: "chat-floating",
    context: { content: { workspace_id: "default", payload: { mode: "fixed-right", navigation_scope: windowId, thread_id: threadId } } },
  }, window.location.origin), { windowId, threadId: SESSION_ID });
  await expect(page.locator(".chat-floating-widget-stack")).toHaveClass(/is-fixed-right/);
  await expect(page.locator(".chat-floating-window-slot:not([hidden])")).toHaveCount(1);
  await expect(page.locator(".chat-floating-window-slot:not([hidden])").getByRole("textbox")).toHaveText("Unsent work survives docking");
  await expect(page.locator(".chat-floating-window-slot")).toHaveCount(2);
  expect(submissions).toHaveLength(0);
  await page.screenshot({ path: "/tmp/maverick-contextual-chat-desktop.png" });
});


test.describe("desktop contextual keyboard", () => {
  test.use({ viewport: { width: 480, height: 844 }, hasTouch: false });
  for (const mode of ["overlay", "fixed-right"]) {
    test(`Enter submits and Shift+Enter inserts a newline in ${mode}`, async ({ page }) => {
      const submissions = await installActiveTurn(page, mode);
      await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
      const composer = page.getByRole("textbox");
      await expect(composer).toBeEditable();
      await composer.fill("First line");
      await composer.press("Shift+Enter");
      await expect(composer).toHaveText("First line\n");
      expect(submissions).toHaveLength(0);
      await page.keyboard.insertText("Second line");
      await expect.poll(() => composer.evaluate((element) => (element as HTMLElement).innerText)).toBe("First line\nSecond line");
      await composer.press("Enter");
      await expect.poll(() => submissions.at(-1)?.input_text).toBe("First line\nSecond line");
      await expect(composer).toHaveText("");
      expect(submissions).toHaveLength(1);
    });
  }
});

test("uses the sidebar row/editor and preserves project changes", async ({ page }) => {
  const mutations: Record<string, unknown>[] = [];
  await installActiveTurn(page, "overlay", mutations);
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await page.getByRole("button", { name: "Choose chat", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Choose chat", exact: true });
  await dialog.getByRole("button", { name: "Choose chat view", exact: true }).click();
  await page.getByRole("menuitemradio", { name: /^Recent/ }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Choose chat view", exact: true })).toContainText("Recent");
  const row = dialog.locator(".bs-chat-list__item");
  await expect(row).toHaveCount(1);
  await row.hover();
  await row.getByRole("button", { name: "Edit Active work", exact: true }).click();
  await expect(dialog.locator(".bs-chat-thread-editor")).toBeVisible();
  await dialog.getByRole("textbox", { name: "Edit title Active work" }).fill("Renamed work");
  await dialog.getByRole("combobox", { name: "Project", exact: true }).selectOption("project-demo");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(() => mutations.at(-1)).toMatchObject({ action: "rename", title: "Renamed work", project_id: "project-demo" });
  await expect(dialog.locator(".bs-chat-thread-editor")).toHaveCount(0);
  await page.screenshot({ path: "/tmp/maverick-chat-shared-picker-desktop.png" });
});

test("resets the real controller after deleting a promoted draft", async ({ page }) => {
  const mutations: Record<string, unknown>[] = [];
  const submissions = await installActiveTurn(page, "overlay", mutations);
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  const slot = page.locator(".chat-floating-window-slot").last();
  const windowId = await slot.getAttribute("data-window-id");
  await expect(slot.getByRole("textbox")).toBeEditable();
  await page.evaluate(({ windowId, threadId }) => window.postMessage({
    type: "maverick.chat.active-thread-changed", owner_app_id: "chat", navigation_scope: windowId, active_thread_id: threadId,
  }, window.location.origin), { windowId, threadId: SESSION_ID });
  await expect(slot.getByRole("button", { name: "Choose chat", exact: true })).toContainText("Active work");
  await slot.getByRole("button", { name: "Choose chat", exact: true }).click();
  const dialog = slot.getByRole("dialog", { name: "Choose chat", exact: true });
  await dialog.getByRole("button", { name: "Expand all projects", exact: true }).click();
  await dialog.locator(".bs-chat-list__item").hover();
  await dialog.getByRole("button", { name: "Edit Active work", exact: true }).click();
  await dialog.getByRole("button", { name: "Delete Active work", exact: true }).click();
  expect(mutations).toHaveLength(0);
  await dialog.getByRole("button", { name: "Delete chat", exact: true }).click();
  await expect.poll(() => mutations.at(-1)?.action).toBe("delete");
  await expect(dialog.locator(".bs-chat-thread-editor")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Search chats", exact: true }).press("Escape");
  await expect(dialog).toBeHidden();
  await expect(slot.getByRole("button", { name: "Choose chat", exact: true })).toContainText("New chat");
  await expect(slot.getByText("I am still working.", { exact: true })).toBeHidden();
  await expect(slot.locator(".chatapp-composer__editor")).toBeEditable();
  expect(submissions).toHaveLength(0);
});


test.describe("mobile shared chat picker", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("reveals the sidebar editor with the same long-press gesture", async ({ page }) => {
    await installActiveTurn(page, "mobile-fullscreen");
    await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
    const trigger = page.getByRole("button", { name: "Choose chat", exact: true });
    await expect(trigger).not.toContainText("Working");
    await trigger.tap();
    const dialog = page.getByRole("dialog", { name: "Choose chat", exact: true });
    await dialog.getByRole("button", { name: "Expand all projects", exact: true }).tap();
    const rowButton = dialog.locator(".bs-chat-list__select-button");
    await rowButton.dispatchEvent("pointerdown", { pointerId: 1, pointerType: "touch", clientX: 30, clientY: 100 });
    await expect(dialog.locator(".chat-floating-thread-picker")).toHaveClass(/has-thread-actions-revealed/);
    await rowButton.dispatchEvent("pointerup", { pointerId: 1, pointerType: "touch", clientX: 30, clientY: 100 });
    await dialog.getByRole("button", { name: "Edit Active work", exact: true }).tap();
    await expect(dialog.locator(".bs-chat-thread-editor")).toBeVisible();
    await expect(dialog.getByRole("combobox", { name: "Project", exact: true })).toBeVisible();
    await page.screenshot({ path: "/tmp/maverick-chat-shared-picker-mobile.png" });
    await dialog.getByRole("button", { name: "Cancel", exact: true }).tap();
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(".bs-chat-thread-editor")).toHaveCount(0);
  });
});
