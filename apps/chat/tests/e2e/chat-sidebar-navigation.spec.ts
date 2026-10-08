import { expect, test } from "@playwright/test";

const NOW = "2026-10-08T10:00:00.000Z";

for (const width of [280, 390]) {
  test(`navigates categories and project dropdowns with Busy animations at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const projects = [
      {
        project_id: "alpha",
        name: "Product",
        created_at: NOW,
        updated_at: NOW,
      },
      {
        project_id: "beta",
        name: "Research notes",
        created_at: NOW,
        updated_at: NOW,
      },
    ];
    const threads = [
      {
        thread_id: "busy",
        title: "Build the new sidebar",
        project_id: "alpha",
        availability: "busy",
      },
      {
        thread_id: "research",
        title: "Market research",
        project_id: "beta",
        runtime_profile: "research",
      },
      {
        thread_id: "senses",
        title: "Visual question",
        project_id: "alpha",
        source_app_id: "senses",
        has_unread_completed_response: true,
      },
      {
        thread_id: "design",
        title: "Dashboard design",
        source_app_id: "design-studio",
      },
      { thread_id: "mac", title: "Organize desktop", device_use_enabled: true },
      { thread_id: "multi", title: "Team analysis" },
    ].map((thread) => ({
      runtime_session_id: `session-${thread.thread_id}`,
      source_app_id: "chat",
      agent_label: "Chat",
      agent_role_id: "",
      agent_type_id: "",
      system_prompt: "",
      project_id: null,
      archived: false,
      availability: "free",
      created_at: NOW,
      updated_at: NOW,
      ...thread,
    }));
    const mutations: Record<string, unknown>[] = [];
    const browserErrors: string[] = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    await page.route(/^http:\/\/[^/]+\/api\//, async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const body = request.method() === "POST" ? request.postDataJSON() : {};
      const json = (payload: unknown) => route.fulfill({ json: payload });
      if (url.pathname === "/api/apps/chat/backend") {
        if (body.action === "pwa.read_model")
          return json({
            revision: "projects-v1",
            payload: { kind: "projects", data: { projects, has_more: false } },
          });
        if (body.action === "view_filter" || body.action === "set_view_filter")
          return json({ state: { view_filter: { query: body.query || "" } } });
        if (body.action === "projects.update") {
          mutations.push(body);
          const project = projects.find(
            (item) => item.project_id === body.project_id,
          )!;
          project.name = body.name;
          return json({ project, projects });
        }
        if (body.action === "projects.create") {
          mutations.push(body);
          const project = {
            project_id: "new",
            name: body.name,
            created_at: NOW,
            updated_at: NOW,
          };
          projects.push(project);
          return json({ project, projects });
        }
      }
      if (url.pathname === "/api/inter-agent/runs")
        return json({ items: [{ run: { thread_id: "multi" } }] });
      if (url.pathname === "/api/runtime/threads")
        return json({ threads, workspace_id: "default" });
      if (url.pathname.endsWith("/events")) return json({ items: [] });
      throw new Error(
        `Unexpected sidebar request: ${request.method()} ${url.pathname} ${body.action || ""}`,
      );
    });
    await page.routeWebSocket("**/ws/runtime/threads", (connection) => {
      connection.send(
        JSON.stringify({
          type: "runtime.thread.snapshot",
          workspace_id: "default",
          threads,
          at: NOW,
        }),
      );
    });
    await page.goto(
      `/apps/chat/widgets/chat-sidebar/index.html?maverick_theme=${width === 390 ? "light" : "dark"}`,
      {
        waitUntil: "domcontentloaded",
      },
    );
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(6);
    await expect(
      page.getByRole("button", { name: "Choose chat view" }),
    ).toContainText("All conversations");
    await expect(
      page.locator(".dashboard-sidebar__disclosure[inert]"),
    ).toHaveCount(3);
    await expect(
      page.getByRole("button", { name: "Expand all projects" }),
    ).toBeEnabled();
    await page.screenshot({
      path: testInfo.outputPath(`sidebar-default-${width}.png`),
    });
    await page
      .getByRole("button", { name: "Show chats in project Product" })
      .click();
    await expect(
      page.getByRole("button", { name: "Build the new sidebar", exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(".dashboard-sidebar__disclosure[inert]"),
    ).toHaveCount(2);
    await page
      .getByRole("button", { name: "Hide chats in project Product" })
      .click();
    await page.getByRole("button", { name: "Expand all projects" }).click();
    const busyRow = page.locator(".bs-chat-list__item.is-busy");
    await expect(busyRow.locator(".bs-chat-list__glow-layer")).toHaveCount(6);
    expect(
      await busyRow
        .locator(".bs-chat-list__glow-layer--rim")
        .evaluate(
          (element) => getComputedStyle(element, "::before").animationName,
        ),
    ).toBe("bs-chat-glow-rotate");
    await page.screenshot({
      path: testInfo.outputPath(`sidebar-${width}.png`),
    });

    const viewSwitcher = page.getByRole("button", { name: "Choose chat view" });
    const searchTrigger = page.getByRole("button", {
      name: "Search chats",
      exact: true,
    });
    await expect(viewSwitcher).not.toContainText("Chat");
    const viewBounds = await viewSwitcher.boundingBox();
    const searchBounds = await searchTrigger.boundingBox();
    expect(Math.abs(viewBounds!.y - searchBounds!.y)).toBeLessThan(1);
    for (const name of ["Collapse all projects", "New project"]) {
      const actionBounds = await page
        .getByRole("button", { name, exact: true })
        .boundingBox();
      expect(
        Math.abs(
          actionBounds!.y +
            actionBounds!.height / 2 -
            (viewBounds!.y + viewBounds!.height / 2),
        ),
      ).toBeLessThan(1);
      expect(actionBounds!.x).toBeGreaterThanOrEqual(
        viewBounds!.x + viewBounds!.width,
      );
      expect(actionBounds!.x + actionBounds!.width).toBeLessThanOrEqual(
        searchBounds!.x,
      );
    }
    expect(searchBounds!.x).toBeGreaterThanOrEqual(
      viewBounds!.x + viewBounds!.width,
    );
    await searchTrigger.click();
    const expandedSearch = page.getByRole("textbox", { name: "Search chats" });
    await expect(expandedSearch).toBeFocused();
    await expect(viewSwitcher).toBeHidden();
    await expect(
      page.locator(".dashboard-sidebar__toolbar-actions"),
    ).toBeHidden();
    const searchFrame = page.locator(".bs-chat-sidebar-search-frame");
    expect((await searchFrame.boundingBox())!.width).toBeGreaterThan(
      viewBounds!.width,
    );
    await page.screenshot({
      path: testInfo.outputPath(`sidebar-search-${width}.png`),
    });
    await expandedSearch.press("Escape");
    await expect(viewSwitcher).toBeVisible();
    await expect(searchTrigger).toBeFocused();

    await searchTrigger.click();
    await expandedSearch.fill("Market research");
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(1);
    await page.locator(".bs-chat-list__select-button").first().focus();
    await expect(viewSwitcher).toBeVisible();
    await expect(searchTrigger).toHaveAttribute(
      "title",
      "Search: Market research",
    );
    await searchTrigger.click();
    await expect(expandedSearch).toHaveValue("Market research");
    await expandedSearch.press("Escape");
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(6);

    await page.getByRole("button", { name: "Choose chat view" }).click();
    const menu = page.getByRole("menu");
    await expect(menu.getByRole("menuitemradio")).toHaveCount(8);
    await expect
      .poll(() => menu.evaluate((element) => getComputedStyle(element).opacity))
      .toBe("1");
    await expect(
      menu.getByRole("menuitemradio", { name: "Multi-agent" }),
    ).toContainText("1");
    expect(
      await menu.evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      ),
    ).toBe(width === 390 ? "rgb(255, 255, 255)" : "rgb(12, 12, 14)");
    const bounds = await menu.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: testInfo.outputPath(`sidebar-menu-${width}.png`),
    });
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Choose chat view" }),
    ).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(menu).toBeVisible();
    await expect(
      menu.getByRole("menuitemradio", { name: "All conversations" }),
    ).toBeFocused();
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    await expect(
      menu.getByRole("menuitemradio", { name: "Recent" }),
    ).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(
      menu.getByRole("menuitemradio", { name: "Unread & active" }),
    ).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(
      menu.getByRole("menuitemradio", { name: "Research" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("button", { name: "Choose chat view" }),
    ).toContainText("Research");
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(1);
    await expect(page.locator(".bs-chat-list__title")).toHaveText(
      "Market research",
    );

    await page.getByRole("button", { name: "Choose chat view" }).click();
    await page
      .getByRole("menuitemradio", { name: "All conversations" })
      .click();
    await expect(
      page.locator(".dashboard-sidebar__disclosure[inert]"),
    ).toHaveCount(3);
    await page.getByRole("button", { name: "Expand all projects" }).click();
    await page.getByRole("button", { name: "Collapse all projects" }).click();
    await expect(
      page.locator(".dashboard-sidebar__disclosure[inert]"),
    ).toHaveCount(3);
    await expect(
      page.getByRole("button", { name: "Build the new sidebar", exact: true }),
    ).toHaveCount(0);
    await expect
      .poll(() =>
        page.locator(".bs-chat-folder__header").evaluateAll((headers) => {
          const first = headers[0].getBoundingClientRect();
          const second = headers[1].getBoundingClientRect();
          return second.top - first.top;
        }),
      )
      .toBeLessThanOrEqual(40);
    await page.screenshot({
      path: testInfo.outputPath(`sidebar-collapsed-${width}.png`),
    });
    await page.getByRole("button", { name: "Expand all projects" }).click();
    await expect(
      page.getByRole("button", { name: "Build the new sidebar", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Hide chats in project Product" })
      .click();
    await expect(
      page.getByRole("button", { name: "Show chats in project Product" }),
    ).toHaveAttribute("aria-expanded", "false");

    await page.keyboard.press("Control+k");
    const search = page.getByRole("textbox", { name: "Search chats" });
    await expect(search).toBeFocused();
    await search.fill("Build the new sidebar");
    await expect(
      page.getByRole("button", { name: "Build the new sidebar", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(1);
    await page.getByRole("button", { name: "Clear chat search" }).click();
    await expect(search).toBeFocused();
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(6);

    await page
      .getByRole("button", { name: "Project actions for Product" })
      .click();
    await page.getByRole("menuitem", { name: "Rename project" }).click();
    const rename = page.getByRole("textbox", {
      name: "Rename project Product",
    });
    await expect(rename).toBeFocused();
    await rename.fill("Product launch");
    await rename.press("Enter");
    await expect(
      page.getByRole("button", {
        name: "Show chats in project Product launch",
      }),
    ).toBeVisible();
    expect(mutations).toContainEqual({
      action: "projects.update",
      project_id: "alpha",
      name: "Product launch",
    });

    await page
      .getByRole("button", { name: "Project actions for Product launch" })
      .click();
    await page.getByRole("menuitem", { name: "Delete project" }).click();
    await expect(page.locator(".bs-chat-project-delete-confirm")).toBeVisible();
    await page
      .locator(".bs-chat-project-delete-confirm")
      .getByRole("button", { name: "Cancel" })
      .click();
    await expect(page.locator(".bs-chat-project-delete-confirm")).toHaveCount(
      0,
    );
    await page.getByRole("button", { name: "Cancel project changes" }).click();
    await page.getByRole("button", { name: "Choose chat view" }).click();
    await page.getByRole("menuitemradio", { name: "Research" }).click();
    await page
      .getByRole("button", { name: "New project", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Show chats in project New project" }),
    ).toBeVisible();
    expect(mutations).toContainEqual({
      action: "projects.create",
      name: "New project",
    });
    expect(browserErrors).toEqual([]);
  });
}
