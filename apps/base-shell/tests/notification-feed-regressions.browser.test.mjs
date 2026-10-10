import assert from "node:assert/strict";
import { resolve } from "node:path";
import { test } from "node:test";
import { browserExecutable, close, listen } from "./browser-contract-support.mjs";
import { chromium, fixtureServer } from "./shell-presentation-fixture.mjs";

test("updated calendar sheets, long codes and rectangular logos remain visible", {
  timeout: 60_000,
}, async () => {
  const server = fixtureServer([]);
  const origin = await listen(server);
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      executablePath: browserExecutable() || undefined,
      args: ["--no-sandbox"],
    });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let notifications = [];
    let socket;
    await page.routeWebSocket("**/api/apps/events/ws", (ws) => {
      socket = ws;
    });
    await page.route("**/api/apps/chat/backend", (route) =>
      route.fulfill({
        json: {
          notifications,
          total: notifications.length,
          unread_total: notifications.length,
          capabilities: {},
        },
      }),
    );
    const logo = `data:image/svg+xml,${encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="24"><rect width="96" height="24" fill="red"/></svg>',
    )}`;
    await page.route("**/api/apps", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.items.find((app) => app.app_id === "chat").logo = {
        kind: "image",
        value: logo,
      };
      await route.fulfill({ json: body });
    });
    const refresh = async (rows) => {
      notifications = rows;
      assert.ok(socket, "Notification event socket is connected");
      socket.send(JSON.stringify({
          type: "maverick.app.data-changed",
          owner_app_id: "chat",
          resource: "notifications",
          workspace_id: "default",
      }));
    };
    const screenshot = async (name) => {
      if (process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR)
        await page.screenshot({
          path: resolve(process.env.MAVERICK_SIDEBAR_SCREENSHOT_DIR, name),
        });
    };
    await page.goto(`${origin}/app/canvas`);
    await page
      .getByRole("button", { name: "Controlli workspace", exact: true })
      .hover();
    await page.getByRole("button", { name: "Notifiche", exact: true }).click();
    await page.getByText("Nessuna notifica", { exact: true }).waitFor();
    const calendar = {
      id: "calendar",
      title: "Updated appointment",
      presentation: { kind: "calendar", date: "2026-10-15" },
    };
    await refresh([calendar]);
    const sheet = page.locator('[data-detail="calendar"] [aria-label]');
    const settled = () =>
      page.waitForFunction(() => {
        const sheets = [...document.querySelectorAll("[data-sheets] > div")];
        return sheets.length === 4 && sheets.every(
          (element) => getComputedStyle(element).opacity === "0",
        );
      });
    await page.locator('[aria-label="2026-10-15"]').waitFor();
    await settled();
    await refresh([{
      ...calendar,
      presentation: { kind: "calendar", date: "2026-10-20" },
    }]);
    await page.locator('[aria-label="2026-10-20"]').waitFor();
    await settled();
    assert.match(await sheet.locator(":scope > div").first().innerText(), /\b20\b/);
    const image = page.locator("[data-notification] img");
    await image.evaluate((element) => element.decode());
    assert.deepEqual(await image.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return [
        element.naturalWidth,
        element.naturalHeight,
        rect.width,
        rect.height,
        getComputedStyle(element).objectFit,
      ];
    }), [96, 24, 24, 24, "contain"]);
    await screenshot("notification-regressions-desktop.png");

    // Start with settled details so geometry also covers reduced motion.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 320, height: 640 });
    const mobileBell = page.locator(
      ".bs-mobile-shell-header__button.bs-notifications__toggle",
    );
    await mobileBell.waitFor({ state: "visible" });
    await mobileBell.click();
    const code = { id: "code", title: "Verification code" };
    for (const value of ["482913", "12345678", "AB12CD34EF56GH78IJ90"]) {
      await refresh([{ ...code, presentation: { kind: "code", code: value } }]);
      const detail = page.locator('[data-detail="code"]');
      await page.getByRole("img", {
        name: `Codice ${[...value].join(" ")}`,
        exact: true,
      }).waitFor();
      await detail.scrollIntoViewIfNeeded();
      const geometry = await detail.evaluate((element) => {
        const containers = [
          element,
          element.closest("article"),
          element.closest('[role="list"]'),
          element.closest('[data-slot="live-notification-feed"]'),
          element.closest(".bs-notifications__inbox"),
        ].map((container) => container.getBoundingClientRect());
        const left = Math.max(...containers.map((rect) => rect.left));
        const right = Math.min(...containers.map((rect) => rect.right));
        const top = Math.max(0, ...containers.map((rect) => rect.top));
        const bottom = Math.min(
          innerHeight,
          ...containers.map((rect) => rect.bottom),
        );
        const digits = [...element.querySelectorAll("[data-digit]")];
        return {
          text: digits.map((digit) => digit.textContent).join(""),
          rows: new Set(
            digits.map((digit) => digit.getBoundingClientRect().top),
          ).size,
          visible: digits.every((digit) => {
            const glyph = digit.getBoundingClientRect();
            const cell = digit.parentElement.getBoundingClientRect();
            const detail = element.getBoundingClientRect();
            return glyph.width > 0 && glyph.left >= left && glyph.right <= right
              && glyph.left >= cell.left && glyph.right <= cell.right
              && glyph.top >= top && glyph.bottom <= bottom
              && glyph.top >= detail.top && glyph.bottom <= detail.bottom;
          }),
        };
      });
      assert.equal(geometry.text, value);
      assert.equal(
        geometry.visible,
        true,
        `${value.length} characters fit their cells and clipping containers at 320px`,
      );
      if (value.length === 6) assert.equal(geometry.rows, 1);
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      await detail.locator("[data-copy]").click();
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), value);
      await screenshot(`notification-code-${value.length}-mobile.png`);
    }
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser?.close();
    await close(server);
  }
});
