import { expect, test, type Page } from "@playwright/test";
import type { ScheduledChat, ScheduledConfig } from "../../frontend/src/api/scheduledChats";

const timestamp = "2026-10-13T10:00:00Z";
function fixture(): ScheduledChat {
  return { id: "schedule-1", title: "Daily brief", instructions: "Review the day and prepare a brief.",
    graph: { nodes: [
      { id: "calendar", title: "Review calendar", instructions: "Check today's meetings.", skill_ids: [], position: { x: 100, y: 100 } },
      { id: "mail", title: "Review inbox", instructions: "Find important unread emails.", skill_ids: [], position: { x: 100, y: 300 } },
      { id: "brief", title: "Prepare brief", instructions: "Combine the findings.", skill_ids: [], position: { x: 460, y: 170 } },
    ], edges: [{ id: "calendar-brief", source: "calendar", target: "brief" }, { id: "mail-brief", source: "mail", target: "brief" }] },
    schedule: { frequency: "weekdays", timezone: "Europe/Rome", time: "08:00", weekday: 0, date: "" },
    workspace_profile_binding_id: "", reasoning_effort: "", project_id: "", conversation_mode: "new", notifications: true,
    revision: 1, status: "active", next_run_at: "2026-10-14T06:00:00Z", chat_session_id: "management-chat",
    created_at: timestamp, updated_at: timestamp, run_status: null, run: null, history: [], message_status: "completed",
  };
}

async function installMocks(page: Page) {
  const state = { chats: [fixture()], writes: [] as Record<string, unknown>[] };
  const thread = { thread_id: "management-chat", runtime_session_id: "management-chat", title: "Daily brief",
    source_app_id: "chat", agent_label: "chat", agent_type_id: "chat", agent_role_id: "", system_prompt: "", project_id: null,
    archived: false, availability: "free", created_at: timestamp, updated_at: timestamp };
  const provider = { provider_id: "codex", label: "Codex", kind: "runtime_backend", provider_role: "runtime_engine", status: "active", default_model_family: "gpt" };
  const session = { session_id: "management-chat", workspace_id: "default", agent_id: "chat", status: "ready", effective_mode: "full-access", provider_id: "codex" };
  await page.route("**/material-symbols-rounded.woff2", route => route.fulfill({ path: "../base-shell/frontend/public/material-symbols-rounded.woff2", contentType: "font/woff2" }));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith("/api/")) { await route.continue(); return; }
    const body = route.request().postDataJSON() || {};
    let response: unknown = {};
    if (path === "/api/apps/chat/backend") {
      const chat = state.chats.find(item => item.id === body.chat_id) || state.chats[0];
      if (body.action === "scheduled.list") response = { chats: state.chats };
      else if (body.action === "scheduled.read") response = { chat };
      else if (body.action === "scheduled.create") {
        state.writes.push(body);
        const created = { ...fixture(), ...body, id: body.creation_id, chat_session_id: "management-chat" } as ScheduledChat;
        state.chats.push(created); response = { chat: created };
      } else if (body.action === "scheduled.update") {
        state.writes.push(body);
        Object.assign(chat, body, { revision: chat.revision + 1 }); response = { chat };
      } else if (body.action === "scheduled.pause" || body.action === "scheduled.resume") {
        chat.status = body.action === "scheduled.pause" ? "paused" : "active"; chat.revision++; response = { chat };
      } else if (body.action === "scheduled.run") {
        chat.run = { id: "run-1", status: "checkpoint", created_at: timestamp, finished_at: null,
          steps: chat.graph.nodes.map(node => ({ node_id: node.id, status: node.id === "brief" ? "pending" : "checkpoint", session_id: `work-${node.id}`, turn_id: `turn-${node.id}`, output: "Verified result", error: "" })) };
        response = { chat };
      } else if (body.action === "scheduled.continue") {
        state.writes.push(body); chat.run!.status = "running";
        chat.run!.steps = chat.run!.steps.map(step => ({ ...step, status: step.node_id === "brief" ? "running" : "completed" }));
        response = { chat };
      } else if (body.action === "projects.list") response = { projects: [] };
      else if (body.action === "pwa.read_model") response = { revision: "projects-1", payload: { kind: "projects", data: { projects: [], has_more: false } } };
    } else if (path === "/api/providers") response = { workspace_id: "default", configured: true, active_provider: provider, items: [provider] };
    else if (path === "/api/apps/dependencies") response = { workspace_id: "default", dependencies: [] };
    else if (path === "/api/apps") response = { items: [] };
    else if (path === "/api/runtime/threads") response = { workspace_id: "default", threads: [thread], has_more: false };
    else if (path.startsWith("/api/runtime/threads/")) response = { thread, threads: [thread] };
    else if (path === "/api/runtime/sessions/management-chat") response = session;
    else if (path.includes("/events")) response = { items: [] };
    else if (path.includes("/turns")) response = { items: [] };
    else if (path.includes("inter-agent")) response = { runs: [] };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  });
  await page.routeWebSocket("**/ws/runtime/threads", ws => setTimeout(() => ws.send(JSON.stringify({ type: "runtime.thread.snapshot", workspace_id: "default", threads: [thread], at: timestamp })), 0));
  await page.routeWebSocket(/\/ws\/runtime\/sessions\//, ws => setTimeout(() => ws.send(JSON.stringify({ type: "runtime.snapshot", session, events: [], turns: [], has_more_before: false })), 0));
  return state;
}

test("creates a schedule, saves manual blocks and keeps the composer below React Flow", async ({ page }) => {
  const state = await installMocks(page);
  await page.goto("/apps/chat/?app_page=scheduled");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Weekly planning");
  await page.getByLabel("What should the agent do?").fill("Review progress and plan the week.");
  await page.getByLabel("Repeat", { exact: true }).selectOption("weekly");
  await page.getByRole("button", { name: "Create", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Weekly planning" })).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await expect(page.locator(".scheduled-composer [role=textbox]")).toBeEditable();
  await page.getByRole("button", { name: "Add block" }).click();
  await page.getByLabel("Title", { exact: true }).fill("Review progress");
  await page.getByLabel("Instructions", { exact: true }).fill("Review the completed work and open questions.");
  await page.getByLabel("Workspace skill IDs").fill("planning, review");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  expect((state.writes.at(-1)!.graph as ScheduledConfig["graph"]).nodes[1].skill_ids).toEqual(["planning", "review"]);
  await page.getByRole("button", { name: "Build with AI" }).click();
  await expect(page.locator(".scheduled-composer [role=textbox]")).toContainText("skill-block graph");
});

test("refreshes an open inspector after AI edits and preserves the new skills on save", async ({ page }) => {
  const state = await installMocks(page);
  await page.goto("/apps/chat/?app_page=scheduled/schedule-1");
  await page.locator('.react-flow__node[data-id="calendar"]').click();
  const skills = page.getByLabel("Workspace skill IDs");
  await skills.fill("old-skill");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);
  state.chats[0].graph.nodes[0].skill_ids = ["ai-skill", "review"];
  state.chats[0].revision++;
  await page.evaluate(() => window.postMessage({ type: "loopino.app.data-changed", owner_app_id: "chat", resource: "scheduled-chats" }, window.location.origin));
  await expect(skills).toHaveValue("ai-skill, review");
  await skills.press("End");
  await skills.pressSequentially(", planning");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect((state.writes.at(-1)!.graph as ScheduledConfig["graph"]).nodes[0].skill_ids).toEqual(["ai-skill", "review", "planning"]);
});

test("stops at checkpoints and confirms only the explicit run and block identities", async ({ page }) => {
  const state = await installMocks(page);
  await page.goto("/apps/chat/?app_page=scheduled/schedule-1");
  await page.getByRole("button", { name: "Run now", exact: true }).click();
  await expect(page.getByText("2 checkpoints ready")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add block" })).toHaveCount(0);
  await page.getByRole("button", { name: "Confirm & continue" }).click();
  expect(state.writes.at(-1)).toMatchObject({ action: "scheduled.continue", run_id: "run-1", node_ids: ["calendar", "mail"] });
  await expect(page.getByText("2 checkpoints ready")).toHaveCount(0);
});

test("opens a work conversation from the schedule and returns without losing navigation", async ({ page }) => {
  await installMocks(page);
  await page.goto("/apps/chat/?app_page=scheduled/schedule-1");
  await expect(page.locator(".scheduled-workspace")).toBeVisible();
  await page.evaluate(() => window.postMessage({ type: "loopino.app.navigate", app_id: "chat", params: { app_page: "threads/management-chat" } }, window.location.origin));
  await expect(page.locator(".scheduled-workspace")).toHaveCount(0);
  await expect(page.locator(".chatapp-composer [role=textbox]")).toBeEditable();
  await expect(page.getByRole("button", { name: "Model: Codex", exact: true })).toBeDisabled();
  await page.evaluate(() => window.postMessage({ type: "loopino.app.navigate", app_id: "chat", params: { app_page: "scheduled/schedule-1" } }, window.location.origin));
  await expect(page.locator(".scheduled-workspace")).toBeVisible();
});

test("keeps search, pause filters and settings focus usable in light mode", async ({ page }) => {
  await installMocks(page);
  await page.goto("/apps/chat/?app_page=scheduled&loopino_theme=light");
  await page.getByRole("button", { name: "Actions for Daily brief" }).click();
  await page.getByRole("menuitem", { name: "Pause", exact: true }).click();
  await page.getByRole("tab", { name: "Paused", exact: true }).click();
  await expect(page.locator(".scheduled-row")).toHaveCount(1);
  await page.getByRole("textbox", { name: "Search scheduled tasks" }).fill("Missing schedule");
  await expect(page.getByRole("heading", { name: "No matching tasks" })).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Title", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("opens task creation directly, cancels to the list and saves to the graph", async ({ page }) => {
  await installMocks(page);
  await page.goto("/apps/chat/?app_page=scheduled/create/new");
  await expect(page.getByRole("dialog", { name: "New scheduled task" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Title", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Scheduled tasks", exact: true })).toBeVisible();
  await page.evaluate(() => window.postMessage({ type: "loopino.app.navigate", app_id: "chat", params: { app_page: "scheduled/create/new" } }, window.location.origin));
  await page.getByLabel("Title", { exact: true }).fill("Task from sidebar");
  await page.getByLabel("What should the agent do?").fill("Review the calendar.");
  await page.getByRole("button", { name: "Create", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Task from sidebar", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

for (const theme of ["dark", "light"]) {
  test(`separates chat and task sidebar blocks with independent controls in ${theme} mode`, async ({ page }) => {
    const state = await installMocks(page);
    state.chats = Array.from({ length: 18 }, (_, index) => ({ ...fixture(), id: `task-${index}`, title: `Task ${index + 1}`, status: index < 12 ? "active" : "paused" }));
    await page.setViewportSize({ width: 320, height: 700 });
    await page.route("**/sidebar-test", route => route.fulfill({ contentType: "text/html", body: `<html style="color-scheme:${theme}"><body style="margin:0;background:${theme === "dark" ? "#171719" : "#edf0f4"}"><iframe title="Chat sidebar" src="/apps/chat/widgets/chat-sidebar/index.html?loopino_theme=${theme}" style="width:100vw;height:100vh;border:0"></iframe><script>window.messages=[];window.addEventListener('message',event=>window.messages.push(event.data));</script></body></html>` }));
    await page.goto("/sidebar-test");
    const sidebar = page.frameLocator('iframe[title="Chat sidebar"]');
    const chats = sidebar.getByRole("region", { name: "Chats", exact: true });
    const tasks = sidebar.getByRole("region", { name: "Scheduled tasks", exact: true });
    await expect(chats.getByRole("button", { name: "Choose chat view" })).toBeVisible();
    await expect(tasks.getByRole("button", { name: "Choose task view" })).toBeVisible();
    await expect(tasks.locator(".scheduled-row")).toHaveCount(18);
    expect(await tasks.evaluate(element => element.previousElementSibling?.getAttribute("aria-label"))).toBe("Chats");
    const first = await chats.boundingBox();
    const second = await tasks.boundingBox();
    expect(second!.y).toBeGreaterThan(first!.y + first!.height);
    const footerClearance = await tasks.evaluate(element => parseFloat(getComputedStyle(element.parentElement!).paddingBottom));
    expect(second!.y + second!.height).toBeLessThanOrEqual(701 - footerClearance);
    await tasks.locator(".scheduled-row__open").last().scrollIntoViewIfNeeded();
    await expect(tasks.getByRole("button", { name: "Choose task view" })).toBeVisible();
    await tasks.getByRole("button", { name: "Choose task view" }).click();
    await sidebar.getByRole("menuitemradio", { name: "Paused tasks" }).click();
    await expect(tasks.locator(".scheduled-row")).toHaveCount(6);
    await expect(chats.getByRole("button", { name: "Choose chat view" })).toContainText("All conversations");
    await tasks.getByRole("button", { name: "Search scheduled tasks", exact: true }).click();
    await tasks.getByRole("textbox", { name: "Search scheduled tasks" }).fill("Task 18");
    await expect(tasks.locator(".scheduled-row")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await tasks.getByRole("button", { name: "Search scheduled tasks", exact: true }).focus();
    await page.keyboard.press("Control+k");
    await expect(chats.getByRole("textbox", { name: "Search chats" })).toBeFocused();
    await expect(tasks.getByRole("textbox")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await tasks.getByRole("button", { name: "New scheduled task" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { messages: { type: string; params?: { app_page: string; new_chat?: boolean } }[] }).messages.some(message => message.type === "loopino.widget.open-app" && message.params?.app_page === "scheduled/create/new" && !message.params.new_chat))).toBe(true);
    await tasks.getByRole("button", { name: "Manage scheduled tasks" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { messages: { type: string; params?: { app_page: string } }[] }).messages.some(message => message.type === "loopino.widget.open-app" && message.params?.app_page === "scheduled"))).toBe(true);
    expect(await tasks.evaluate(element => element.ownerDocument.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
    await page.screenshot({ path: `/tmp/scheduled-tasks-sidebar-${theme}.png` });
  });
}

for (const width of [1440, 390, 320]) {
  test(`graph, inspector and composer stay usable at ${width}px`, async ({ page }) => {
    await installMocks(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/apps/chat/?app_page=scheduled/schedule-1");
    await expect(page.locator(".react-flow__node")).toHaveCount(5);
    await expect(page.locator(".react-flow__edge-path")).toHaveCount(5);
    for (const path of await page.locator(".react-flow__edge-path").all()) expect(await path.getAttribute("d")).not.toContain("NaN");
    const editor = page.locator(".scheduled-composer [role=textbox]");
    await expect(editor).toBeEditable();
    const canvas = await page.locator(".scheduled-canvas").boundingBox();
    const composer = await page.locator(".scheduled-composer").boundingBox();
    expect(canvas!.height).toBeGreaterThan(280);
    expect(composer!.y).toBeGreaterThan(canvas!.y + canvas!.height - 1);
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(901);
    await page.locator('.react-flow__node[data-id="calendar"]').click();
    await expect(page.getByRole("complementary", { name: "Block details", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close block details" }).click();
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.setData("application/x-loopino-scheduled-chat", JSON.stringify({ owner_app_id: "chat", id: "schedule-1", title: "Daily brief" }));
      document.querySelector(".scheduled-composer")!.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: data }));
    });
    await expect(editor).toContainText("Daily brief");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `/tmp/scheduled-chat-${width}.png` });
  });
}
