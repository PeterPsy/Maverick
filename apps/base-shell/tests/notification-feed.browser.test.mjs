import assert from "node:assert/strict";
import { resolve } from "node:path";
import { test } from "node:test";
import {
  browserExecutable,
  close,
  listen,
} from "./browser-contract-support.mjs";
import { chromium, fixtureServer } from "./shell-presentation-fixture.mjs";

const details = [
  { kind: "payment", amount: 48.5, currency: "EUR", accent: "#10b981" },
  {
    kind: "calendar",
    date: "2026-10-15",
    attendees: ["Ava Chen", "Noah Kim"],
    accent: "#ef4444",
  },
  {
    kind: "fitness",
    value: 620,
    goal: 600,
    unit: "kcal",
    streak: 6,
    accent: "#ec4899",
  },
  {
    kind: "delivery",
    steps: ["Packed", "Shipped", "On the way", "Delivered"],
    step: 2,
    accent: "#f59e0b",
  },
  {
    kind: "message",
    from: "Jules Moreau",
    text: "Running five minutes late.",
    accent: "#3b82f6",
  },
  {
    kind: "code",
    code: "482913",
    expires_at: new Date(Date.now() + 300000).toISOString(),
    expiresIn: 300,
    accent: "#6366f1",
  },
  {
    kind: "ride",
    minutes: 2,
    vehicle: "White sedan",
    plate: "7KX 204",
    accent: "#a855f7",
  },
  {
    kind: "flight",
    from: "ICN",
    to: "NRT",
    gate: "C4",
    previousGate: "B12",
    accent: "#0ea5e9",
  },
];

test(
  "live notification feed renders all details, receipts and actions in desktop/mobile themes",
  { timeout: 60_000 },
  async () => {
    const requests = [];
    const server = fixtureServer(requests, {
      notifications: details.map((presentation, index) => ({
        id: presentation.kind,
        title: `Notification ${presentation.kind}`,
        created_at: `2026-10-10T10:${String(index).padStart(2, "0")}:00Z`,
        presentation,
        ...(presentation.kind === "calendar"
          ? { actions: [{ id: "accept", label: "Accetta", done: "Accettato" }] }
          : {}),
      })),
      capabilities: { read: true, actions: true },
    });
    const origin = await listen(server);
    let browser;
    try {
      browser = await chromium.launch({
        headless: true,
        executablePath: browserExecutable() || undefined,
        args: ["--no-sandbox"],
      });
      const errors = [];
      const context = await browser.newContext({
        viewport: { width: 1440, height: 900 },
        serviceWorkers: "block",
      });
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`${origin}/app/canvas`);
      await page
        .getByRole("button", { name: "Controlli workspace", exact: true })
        .hover();
      await page
        .getByRole("button", { name: "Notifiche (8)", exact: true })
        .click();
      const feed = page.locator('[data-slot="live-notification-feed"]');
      await feed.waitFor({ state: "visible" });
      await page
        .getByRole("button", { name: "Mostra altre notifiche", exact: true })
        .click();
      await page.waitForFunction(
        () => document.querySelectorAll("[data-notification]").length === 8,
      );
      assert.equal(await feed.locator("[data-notification]").count(), 8);
      for (const { kind } of details)
        assert.equal(
          await feed.locator(`[data-detail="${kind}"]`).count(),
          1,
          kind,
        );
      const card = feed.locator("article").first();
      assert.deepEqual(
        await card.evaluate((element) => {
          const style = getComputedStyle(element);
          return [style.borderRadius, style.padding, style.backgroundColor];
        }),
        ["16px", "12px", "rgb(23, 23, 23)"],
      );
      if (process.env.LOOPINO_SIDEBAR_SCREENSHOT_DIR)
        await page.screenshot({
          path: resolve(
            process.env.LOOPINO_SIDEBAR_SCREENSHOT_DIR,
            "notification-feed-desktop-dark.png",
          ),
        });
      await page.getByRole("button", { name: "Accetta", exact: true }).click();
      await page.getByText("Accettato", { exact: true }).waitFor();
      await page
        .getByRole("button", { name: "Segna lette", exact: true })
        .click();
      await page.waitForFunction(
        () =>
          document
            .querySelector('[data-slot="live-notification-feed"]')
            ?.getAttribute("data-unread") === "0",
      );
      assert.equal(await feed.locator("[data-unread]").count(), 0);
      await page.keyboard.press("Escape");
      await page
        .getByRole("button", { name: "Controlli Loopino", exact: true })
        .hover();
      await page
        .getByRole("button", { name: "Light mode", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Controlli workspace", exact: true })
        .hover();
      await page
        .getByRole("button", { name: "Notifiche", exact: true })
        .click();
      assert.equal(
        await card.evaluate(
          (element) => getComputedStyle(element).backgroundColor,
        ),
        "rgb(255, 255, 255)",
      );
      if (process.env.LOOPINO_SIDEBAR_SCREENSHOT_DIR)
        await page.screenshot({
          path: resolve(
            process.env.LOOPINO_SIDEBAR_SCREENSHOT_DIR,
            "notification-feed-desktop-light.png",
          ),
        });
      await context.close();

      const mobile = await browser.newContext({
        viewport: { width: 320, height: 640 },
        isMobile: true,
        hasTouch: true,
        reducedMotion: "reduce",
        serviceWorkers: "block",
      });
      const mobilePage = await mobile.newPage();
      mobilePage.on("pageerror", (error) => errors.push(error.message));
      await mobilePage.goto(`${origin}/app/canvas`);
      await mobilePage
        .getByRole("button", { name: "Notifiche", exact: true })
        .tap();
      await mobilePage
        .getByRole("button", { name: "Mostra altre notifiche", exact: true })
        .tap();
      await mobilePage.waitForFunction(
        () => document.querySelectorAll("[data-notification]").length === 8,
      );
      const inbox = mobilePage.getByRole("region", {
        name: "Notifiche da leggere",
      });
      const box = await inbox.boundingBox();
      assert.ok(
        box.x >= 12 && box.x + box.width <= 308 && box.y + box.height <= 640,
      );
      assert.equal(await mobilePage.locator("[data-notification]").count(), 8);
      assert.equal(
        await mobilePage
          .locator("[data-dismiss]")
          .first()
          .evaluate((element) => getComputedStyle(element).opacity),
        "1",
      );
      const overflow = await mobilePage
        .locator('[data-slot="live-notification-feed"]')
        .evaluate((element) => element.scrollWidth > element.clientWidth);
      assert.equal(overflow, false);
      const digitRows = await mobilePage
        .locator("[data-digit]")
        .evaluateAll((digits) =>
          digits.map((digit) => digit.getBoundingClientRect().top),
        );
      assert.equal(
        new Set(digitRows).size,
        1,
        "Code digits stay on one row at 320px",
      );
      if (process.env.LOOPINO_SIDEBAR_SCREENSHOT_DIR)
        await mobilePage.screenshot({
          path: resolve(
            process.env.LOOPINO_SIDEBAR_SCREENSHOT_DIR,
            "notification-feed-mobile.png",
          ),
        });
      await mobilePage
        .getByRole("button", {
          name: "Chiudi notifica: Notification flight",
          exact: true,
        })
        .tap();
      await mobilePage
        .locator('[data-kind="flight"]')
        .waitFor({ state: "detached" });
      assert.deepEqual(errors, []);
      await mobile.close();
    } finally {
      await browser?.close();
      await close(server);
    }
  },
);
