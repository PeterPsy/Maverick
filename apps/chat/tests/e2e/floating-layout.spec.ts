import { expect, test } from "@playwright/test";
import { installActiveTurn } from "./fixtures/activeTurn";

test("collapsed chat launchers preserve their title width", async ({ page }) => {
  await installActiveTurn(page, "overlay");
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await expect(page.getByRole("textbox")).toBeVisible();
  await page.getByRole("button", { name: "Collapse chat", exact: true }).click();
  await page.setViewportSize({ width: 160, height: 48 });
  const launcher = page.locator(".chat-floating-widget-launcher:visible");
  const geometry = await launcher.evaluate((element) => ({
    width: element.getBoundingClientRect().width,
    height: element.getBoundingClientRect().height,
    flexBasis: getComputedStyle(element).flexBasis,
  }));
  await page.screenshot({ path: "/tmp/loopino-review-04984238-collapsed-one.png" });
  expect(geometry.width).toBeGreaterThanOrEqual(150);
});

test("minimized chat launchers stay clickable below window navigation", async ({ page }) => {
  await installActiveTurn(page, "overlay");
  await page.goto("/apps/chat/widgets/chat-floating/index.html?context=steering-fixture");
  await expect(page.getByRole("textbox")).toBeVisible();
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await page.getByRole("button", { name: "New chat", exact: true }).first().click();
  await expect(page.locator(".chat-floating-window-slot")).toHaveCount(3);
  for (const slot of await page.locator(".chat-floating-window-slot").all()) {
    await slot.getByRole("button", { name: "Collapse chat", exact: true }).click();
  }
  await page.setViewportSize({ width: 504, height: 80 });
  const geometry = await page.locator(".chat-floating-widget-launcher:visible").evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return { centerClickable: Boolean(hit && element.contains(hit)) };
    }),
  );
  await page.screenshot({ path: "/tmp/loopino-review-04984238-collapsed-two.png" });
  expect(geometry.every((item) => item.centerClickable)).toBe(true);
});
