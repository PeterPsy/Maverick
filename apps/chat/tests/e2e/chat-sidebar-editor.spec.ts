import { expect, test } from "@playwright/test";

for (const width of [280, 390]) {
  test.describe(`chat row editor at ${width}px`, () => {
    test.use({
      viewport: { width, height: 844 },
      hasTouch: width === 390,
      isMobile: width === 390,
    });

    test("edits, moves and confirms deletion without losing drafts", async ({
      page,
    }, testInfo) => {
      const now = "2026-10-08T10:00:00.000Z";
      const projects = [
        {
          project_id: "product",
          name: "Product",
          created_at: now,
          updated_at: now,
        },
      ];
      let threads = [
        {
          thread_id: "budget",
          runtime_session_id: "budget-session",
          title: "Budget notes",
          project_id: null as string | null,
          source_app_id: "chat",
          agent_label: "Chat",
          agent_role_id: "",
          agent_type_id: "",
          system_prompt: "",
          archived: false,
          availability: "busy",
          created_at: now,
          updated_at: now,
        },
      ];
      let rejectNextSave = true;
      let saveRequests = 0;
      let deleteRequests = 0;
      const browserErrors: string[] = [];
      page.on("pageerror", (error) => browserErrors.push(error.message));
      await page.route(/^http:\/\/[^/]+\/api\//, async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const body =
          request.method() === "POST" || request.method() === "PATCH"
            ? request.postDataJSON()
            : {};
        const json = (payload: unknown, status = 200) =>
          route.fulfill({ json: payload, status });
        if (url.pathname === "/api/apps/chat/backend") {
          if (body.action === "pwa.read_model")
            return json({
              revision: "projects",
              payload: {
                kind: "projects",
                data: { projects, has_more: false },
              },
            });
          if (body.action === "projects.list") return json({ projects });
          if (
            body.action === "view_filter" ||
            body.action === "set_view_filter"
          )
            return json({
              state: { view_filter: { query: body.query || "" } },
            });
        }
        if (url.pathname === "/api/inter-agent/runs")
          return json({ items: [] });
        if (url.pathname === "/api/runtime/threads")
          return json({ threads, workspace_id: "default" });
        if (
          url.pathname === "/api/runtime/threads/budget" &&
          request.method() === "PATCH"
        ) {
          saveRequests++;
          if (rejectNextSave) {
            rejectNextSave = false;
            return json({ error: "save_unavailable" }, 400);
          }
          threads = [
            { ...threads[0], title: body.title, project_id: body.project_id },
          ];
          return json({
            thread: threads[0],
            changed_thread: threads[0],
            projects,
          });
        }
        if (
          url.pathname === "/api/runtime/threads/budget" &&
          request.method() === "DELETE"
        ) {
          deleteRequests++;
          threads = [];
          return json({ deleted_thread_id: "budget" });
        }
        throw new Error(
          `Unexpected editor request: ${request.method()} ${url.pathname} ${body.action || ""}`,
        );
      });
      await page.routeWebSocket("**/ws/runtime/threads", (connection) =>
        connection.send(
          JSON.stringify({
            type: "runtime.thread.snapshot",
            workspace_id: "default",
            threads,
            at: now,
          }),
        ),
      );
      await page.goto(
        `/apps/chat/widgets/chat-sidebar/index.html?maverick_theme=${width === 390 ? "light" : "dark"}`,
      );
      await expect(
        page.getByRole("button", { name: "Show chats in project Product" }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Expand all projects" }).click();
      const row = page.locator(".bs-chat-list__item");
      await expect(row).toHaveCount(1);
      if (width === 390) {
        await page
          .getByRole("button", { name: "Budget notes", exact: true })
          .click({ trial: true });
        const bounds = await page
          .getByRole("button", { name: "Budget notes", exact: true })
          .boundingBox();
        const touch = await page.context().newCDPSession(page);
        await touch.send("Input.dispatchTouchEvent", {
          type: "touchStart",
          touchPoints: [
            {
              x: bounds!.x + bounds!.width / 2,
              y: bounds!.y + bounds!.height / 2,
            },
          ],
        });
        await expect(
          page.locator(".bs-widget-root.has-thread-actions-revealed"),
        ).toBeVisible();
        await touch.send("Input.dispatchTouchEvent", {
          type: "touchEnd",
          touchPoints: [],
        });
        await touch.detach();
      } else await row.hover();
      await expect
        .poll(() =>
          row
            .locator(".bs-chat-list__selection-toggle")
            .evaluate((element) => getComputedStyle(element).opacity),
        )
        .toBe("1");
      await expect
        .poll(() =>
          row
            .locator(".bs-chat-list__meta")
            .evaluate((element) => getComputedStyle(element).opacity),
        )
        .toBe("0");
      await page.screenshot({
        path: testInfo.outputPath(`row-actions-${width}.png`),
      });
      await page
        .getByRole("button", { name: "Select Budget notes", exact: true })
        .click();
      await expect(
        page.getByRole("button", {
          name: "Deselect Budget notes",
          exact: true,
        }),
      ).toHaveAttribute("aria-pressed", "true");
      await page
        .getByRole("button", { name: "Deselect Budget notes", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Edit Budget notes", exact: true })
        .click();
      const editor = page.getByRole("form", {
        name: "Edit Budget notes",
        exact: true,
      });
      const title = page.getByRole("textbox", {
        name: "Edit title Budget notes",
      });
      await expect(title).toBeFocused();
      await expect(
        page.getByRole("button", { name: "Select Budget notes", exact: true }),
      ).toHaveCount(0);
      await expect(
        editor.getByRole("button", { name: "Save", exact: true }),
      ).toBeDisabled();
      const rowBounds = await row.boundingBox();
      const titleBounds = await title.boundingBox();
      expect(titleBounds!.width).toBeGreaterThan(rowBounds!.width * 0.85);
      expect(
        await title.evaluate(
          (element) => getComputedStyle(element).outlineStyle,
        ),
      ).toBe("none");
      expect(
        await row
          .locator(".bs-chat-list__glow-layer--rim")
          .evaluate(
            (element) => getComputedStyle(element, "::before").animationName,
          ),
      ).toBe("bs-chat-glow-rotate");
      await page.screenshot({
        path: testInfo.outputPath(`thread-editor-${width}.png`),
      });
      await title.fill("   ");
      await expect(
        editor.getByRole("button", { name: "Save", exact: true }),
      ).toBeDisabled();
      await title.fill("Updated budget notes");
      await page
        .getByRole("combobox", { name: "Project", exact: true })
        .selectOption("product");
      await title.press("Enter");
      await expect(editor.getByRole("alert")).toBeVisible();
      await expect(title).toHaveValue("Updated budget notes");
      await expect(
        page.getByRole("combobox", { name: "Project", exact: true }),
      ).toHaveValue("product");
      await page.screenshot({
        path: testInfo.outputPath(`thread-editor-error-${width}.png`),
      });
      await editor.getByRole("button", { name: "Save", exact: true }).click();
      await expect(editor).toHaveCount(0);
      expect(saveRequests).toBe(2);
      await expect(
        page.getByRole("button", { name: "Hide chats in project Product" }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Edit Updated budget notes", exact: true })
        .focus();
      await page
        .getByRole("button", { name: "Edit Updated budget notes", exact: true })
        .click();
      await page
        .getByRole("textbox", { name: "Edit title Updated budget notes" })
        .press("Escape");
      await expect(
        page.getByRole("button", {
          name: "Edit Updated budget notes",
          exact: true,
        }),
      ).toBeFocused();
      await page
        .getByRole("button", { name: "Edit Updated budget notes", exact: true })
        .click();
      await page
        .getByRole("button", {
          name: "Delete Updated budget notes",
          exact: true,
        })
        .click();
      expect(deleteRequests).toBe(0);
      await page.getByRole("button", { name: "Keep chat" }).click();
      expect(deleteRequests).toBe(0);
      await page
        .getByRole("button", {
          name: "Delete Updated budget notes",
          exact: true,
        })
        .click();
      await page.screenshot({
        path: testInfo.outputPath(`thread-editor-delete-${width}.png`),
      });
      await page
        .getByRole("button", { name: "Delete chat", exact: true })
        .click();
      await expect(page.locator(".bs-chat-list__item")).toHaveCount(0);
      expect(deleteRequests).toBe(1);
      expect(browserErrors).toEqual([]);
    });
  });
}
