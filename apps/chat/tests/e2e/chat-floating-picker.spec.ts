import { expect, test } from "@playwright/test";
import { installActiveTurn, SESSION_ID } from "./fixtures/activeTurn";

for (const width of [390, 480]) {
  test.describe("shared conversation panel at " + width + "px", () => {
    test.use({ viewport: { width, height: 844 }, hasTouch: width === 390 });
    test("matches sidebar rows and keeps nested project actions in the picker", async ({ page }, testInfo) => {
      const mutations: Record<string, unknown>[] = [];
      await installActiveTurn(page, width === 390 ? "mobile-fullscreen" : "overlay", mutations);
      await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
      await page.getByRole("button", { name: "Choose chat", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Choose chat", exact: true });
      await expect(dialog.getByRole("button", { name: "Choose chat view" })).toContainText("All conversations");
      await expect(dialog.getByRole("button", { name: "Show chats in project Demo" })).toBeVisible();
      await dialog.getByRole("button", { name: "Expand all projects" }).click();
      const row = dialog.locator(".bs-chat-list__item");
      const metrics = await row.evaluate((element) => {
        const title = element.querySelector(".bs-chat-list__title")!;
        const time = element.querySelector(".bs-chat-list__timestamp")! as HTMLElement;
        return { font: getComputedStyle(title).fontSize, padding: getComputedStyle(element).padding,
          buttonBorder: getComputedStyle(element.querySelector("button")!).borderTopWidth,
          radius: getComputedStyle(element).borderRadius, timeVisible: time.scrollWidth <= time.clientWidth + 1 };
      });
      expect(metrics.timeVisible).toBe(true);
      const normal = await page.context().newPage();
      await installActiveTurn(normal);
      await normal.goto("/apps/chat/widgets/chat-sidebar/index.html");
      await normal.getByRole("button", { name: "Expand all projects" }).click();
      const normalMetrics = await normal.locator(".bs-chat-list__item").evaluate((element) => ({
        font: getComputedStyle(element.querySelector(".bs-chat-list__title")!).fontSize,
        padding: getComputedStyle(element).padding, radius: getComputedStyle(element).borderRadius,
        buttonBorder: getComputedStyle(element.querySelector("button")!).borderTopWidth,
      }));
      expect(metrics).toMatchObject(normalMetrics);
      await normal.screenshot({ path: testInfo.outputPath("normal-sidebar.png") });
      await normal.close();
      const bounds = await dialog.boundingBox();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
      await page.screenshot({ path: testInfo.outputPath("floating-picker.png") });

      await dialog.getByRole("button", { name: "Project actions for Demo" }).click();
      await page.getByRole("menuitem", { name: "Rename project", exact: true }).click();
      await expect(dialog).toBeVisible();
      const name = dialog.getByRole("textbox", { name: "Rename project Demo" });
      await name.fill("Shared project");
      await name.press("Enter");
      await expect.poll(() => mutations.at(-1)?.action).toBe("project-rename");
      await expect(dialog.getByRole("button", { name: "Hide chats in project Shared project" })).toBeVisible();

      await dialog.getByRole("button", { name: "New chat in Shared project", exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect(page.locator(".chat-floating-window-slot")).toHaveCount(2);
      await expect(page.locator(".chat-floating-window-slot").last().getByRole("textbox")).toBeEditable();
      await expect(page.locator(".chat-floating-window-slot").last()).toBeInViewport();
      const state = await page.evaluate(() => JSON.parse(localStorage.getItem("loopino.chat.floating-widget.state.v1:default")!));
      expect(state.windows.at(-1)).toMatchObject({ isDraft: true, draftProjectId: "project-demo" });
    });
  });
}

test("confirms multiple selection locally and resets the deleted window", async ({ page }) => {
  const mutations: Record<string, unknown>[] = [];
  await installActiveTurn(page, "overlay", mutations);
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await page.getByRole("button", { name: "Choose chat", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Choose chat", exact: true });
  await dialog.getByRole("button", { name: "Expand all projects" }).click();
  await dialog.locator(".bs-chat-list__item").hover();
  await dialog.getByRole("button", { name: "Select Active work", exact: true }).click();
  await dialog.getByRole("button", { name: "Delete 1 selected chat", exact: true }).click();
  expect(mutations).toHaveLength(0);
  await expect(dialog.getByRole("group", { name: "Confirm chat deletion" })).toBeVisible();
  await dialog.getByRole("button", { name: "Conferma", exact: true }).click();
  await expect.poll(() => mutations.at(-1)).toEqual({ action: "delete-batch", thread_ids: [SESSION_ID] });
  await expect(dialog.locator(".chat-floating-selection-actions")).toBeHidden();
  await dialog.getByRole("button", { name: "Search chats", exact: true }).press("Escape");
  await expect(page.getByRole("button", { name: "Choose chat", exact: true })).toContainText("New chat");
  await expect(page.getByText("I am still working.", { exact: true })).toBeHidden();
  await expect(page.getByRole("textbox")).toBeEditable();
});

test("bounds the shared picker and scrolls a long group inside it", async ({ page }, testInfo) => {
  await installActiveTurn(page, "mobile-fullscreen");
  const now = "2026-10-14T12:00:00Z";
  const threads = Array.from({ length: 50 }, (_, index) => ({
    thread_id: index === 0 ? SESSION_ID : "scroll-thread-" + index,
    runtime_session_id: index === 0 ? SESSION_ID : "scroll-session-" + index,
    title: "Conversation " + index + " with a deliberately long title",
    source_app_id: "chat", project_id: null, availability: "free",
    created_at: now, updated_at: now, last_user_message_at: now,
  }));
  await page.routeWebSocket("**/ws/runtime/threads", (socket) => socket.send(JSON.stringify({
    type: "runtime.thread.snapshot", workspace_id: "default", threads, at: now,
  })));
  await page.addInitScript((threadId) => localStorage.setItem("loopino.chat.floating-widget.state.v1:default", JSON.stringify({
    version: 1, windows: [{ id: "scroll-window", threadId, isDraft: false, isCollapsed: false }],
  })), SESSION_ID);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await page.getByRole("button", { name: "Choose chat", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Choose chat", exact: true });
  await dialog.getByRole("button", { name: "Expand all projects" }).click();
  await expect(dialog.locator(".bs-chat-list__item")).toHaveCount(50);
  const list = dialog.locator(".bs-chat-list");
  await expect.poll(() => list.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeGreaterThan(0);
  const bounds = await dialog.boundingBox();
  expect(bounds!.height).toBeLessThanOrEqual(482);
  await list.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await dialog.getByRole("button", { name: threads.at(-1)!.title, exact: true }).click({ trial: true });
  await page.screenshot({ path: testInfo.outputPath("long-picker.png") });
});

test("resets retained conversations only after confirming project deletion", async ({ page }) => {
  const mutations: Record<string, unknown>[] = [];
  const submissions = await installActiveTurn(page, "overlay", mutations, "project-demo");
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await page.getByRole("button", { name: "Choose chat", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Choose chat", exact: true });
  await dialog.getByRole("button", { name: "Project actions for Demo" }).click();
  await page.getByRole("menuitem", { name: "Delete project", exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("alert")).toContainText('Delete project "Demo" and 1 linked chat');
  expect(mutations).toHaveLength(0);
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => mutations.at(-1)?.action).toBe("project-delete");
  await expect(dialog.getByRole("button", { name: "Project actions for Demo" })).toBeHidden();
  await dialog.getByRole("button", { name: "Search chats", exact: true }).press("Escape");
  await expect(page.getByRole("button", { name: "Choose chat", exact: true })).toContainText("New chat");
  await expect(page.getByText("I am still working.", { exact: true })).toBeHidden();
  await expect(page.getByRole("textbox")).toBeEditable();
  expect(submissions).toHaveLength(0);
});
