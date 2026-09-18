import { devices, expect, test, type WebSocketRoute } from "@playwright/test";

const NOW = "2026-09-06T00:00:00.000Z";
const projects = Array.from({ length: 27 }, (_, index) => ({
  project_id: `project-${index}`, name: `Named project ${index + 1}`, created_at: NOW, updated_at: NOW,
}));
const threads = projects.map((project, index) => ({
  thread_id: `thread-${index}`, runtime_session_id: `session-${index}`, title: `Chat ${index + 1}`,
  source_app_id: "chat", agent_label: "Chat", agent_type_id: "", agent_role_id: "", system_prompt: "",
  project_id: project.project_id, archived: false, availability: "active", created_at: NOW, updated_at: NOW,
}));

for (const width of [390, 1280]) {
  test(`recovers all 27 project names after a failed read and a healthy thread update at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    let projectReads = 0;
    let socket: WebSocketRoute | undefined;
    let releaseFirstRead!: () => void;
    const firstRead = new Promise<void>((resolve) => { releaseFirstRead = resolve; });
    await page.route(/^http:\/\/[^/]+\/api\//, async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const body = request.method() === "POST" ? request.postDataJSON() : {};
      const json = (payload: unknown, status = 200) => route.fulfill({ status, json: payload });
      if (url.pathname === "/api/apps/chat/backend" && body.action === "pwa.read_model") {
        expect(body.kind).toBe("projects");
        projectReads += 1;
        if (projectReads === 1) {
          await firstRead;
          return json({ error: "fixture_read_failed" }, 500);
        }
        return json({ revision: "projects-v1", payload: { kind: "projects", data: { projects, has_more: false } } });
      }
      if (url.pathname === "/api/apps/chat/backend" && body.action === "view_filter") {
        return json({ state: { view_filter: { query: "" } } });
      }
      if (url.pathname === "/api/inter-agent/runs") return json({ items: [] });
      if (url.pathname === "/api/runtime/threads") {
        return url.searchParams.get("projection") === "display"
          ? json({ revision: "threads-v1", payload: { kind: "threads", data: { threads } } })
          : json({ threads, workspace_id: "default", has_more: false });
      }
      throw new Error(`Unexpected sidebar request: ${request.method()} ${url.pathname}`);
    });
    const snapshot = () => socket!.send(JSON.stringify({ type: "runtime.thread.snapshot", workspace_id: "default", threads, at: NOW }));
    await page.routeWebSocket("**/ws/runtime/threads", (connection) => { socket = connection; snapshot(); });
    await page.goto("/apps/chat/widgets/chat-sidebar/index.html");
    await expect(page.locator(".bs-chat-folder__title")).toHaveText(projects.map(() => "Project"));
    releaseFirstRead();
    const retry = page.getByRole("button", { name: "Reload project names" });
    await expect(retry).toBeVisible();
    await expect.poll(() => Boolean(socket)).toBe(true);
    snapshot(); // A healthy authoritative stream must not hide the independent project failure.
    await expect(retry).toBeVisible();
    expect(projectReads).toBe(1);
    await retry.click();
    await expect(page.locator(".bs-chat-folder__title")).toHaveCount(27);
    await expect.poll(async () => (await page.locator(".bs-chat-folder__title").allTextContents()).sort())
      .toEqual(projects.map((project) => project.name).sort());
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(projectReads).toBe(2);
  });
}

test.describe("mobile filtered chat scrolling", () => {
  const iphone = devices["iPhone 13"];
  test.use({
    deviceScaleFactor: iphone.deviceScaleFactor,
    hasTouch: iphone.hasTouch,
    isMobile: iphone.isMobile,
    userAgent: iphone.userAgent,
    viewport: iphone.viewport,
  });

  test("keeps a single filtered project group vertically scrollable", async ({ page }) => {
    const filteredThreads = Array.from({ length: 40 }, (_, index) => ({
      thread_id: `senses-thread-${index}`,
      runtime_session_id: `senses-session-${index}`,
      title: `Senses chat ${index + 1}`,
      source_app_id: "senses",
      agent_label: "Senses",
      agent_type_id: "",
      agent_role_id: "",
      project_id: null,
      archived: false,
      availability: "free",
      created_at: NOW,
      updated_at: NOW,
    }));
    let socket: WebSocketRoute | undefined;
    await page.route(/^http:\/\/[^/]+\/api\//, async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const body = request.method() === "POST" ? request.postDataJSON() : {};
      const json = (payload: unknown) => route.fulfill({ json: payload });
      if (url.pathname === "/api/apps/chat/backend" && body.action === "pwa.read_model") {
        return json({ revision: "projects-empty", payload: { kind: "projects", data: { projects: [], has_more: false } } });
      }
      if (url.pathname === "/api/apps/chat/backend" && body.action === "view_filter") {
        return json({ state: { view_filter: { query: "" } } });
      }
      if (url.pathname === "/api/inter-agent/runs") return json({ items: [] });
      if (url.pathname === "/api/runtime/threads") return json({ threads: filteredThreads, workspace_id: "default" });
      throw new Error(`Unexpected sidebar request: ${request.method()} ${url.pathname}`);
    });
    await page.routeWebSocket("**/ws/runtime/threads", (connection) => {
      socket = connection;
      connection.send(JSON.stringify({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: filteredThreads,
        at: NOW,
      }));
    });

    await page.goto("/apps/chat/widgets/chat-sidebar/index.html");
    await expect.poll(() => Boolean(socket)).toBe(true);
    await page.getByRole("button", { name: "Senses chats" }).click();
    await expect(page.locator(".bs-chat-list__item")).toHaveCount(filteredThreads.length);

    const list = page.locator(".bs-chat-list");
    const metrics = await list.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      touchAction: getComputedStyle(element).touchAction,
    }));
    expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight);
    expect(metrics.touchAction).toBe("pan-y");
    await list.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
    await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  });
});
