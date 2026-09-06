import { expect, test, type Page } from "@playwright/test";

const SESSION_ID = "session-steering-browser";
const TURN_ID = "turn-still-working";
const NOW = "2026-09-06T00:00:00.000Z";

async function installActiveTurn(page: Page, widgetMode = "overlay") {
  const submissions: Record<string, unknown>[] = [];
  const session = {
    session_id: SESSION_ID, workspace_id: "default", agent_id: "chat",
    source_app_id: "chat", status: "running", effective_mode: "sandbox",
  };
  const thread = {
    thread_id: SESSION_ID, runtime_session_id: SESSION_ID, title: "Active work",
    source_app_id: "chat", agent_label: "Chat", agent_type_id: "", agent_role_id: "",
    system_prompt: "", project_id: null, archived: false, availability: "active",
    created_at: NOW, updated_at: NOW, last_user_message_at: NOW,
  };
  const turn = {
    turn_id: TURN_ID, session_id: SESSION_ID, workspace_id: "default", status: "active",
    input_text: "Keep working", failure_reason: null, created_at: NOW, updated_at: NOW,
  };
  const event = (eventType: string, payload: Record<string, unknown>, id = eventType) => ({
    event_id: id, session_id: SESSION_ID, turn_id: TURN_ID,
    event_type: eventType, payload, created_at: NOW,
  });
  const events = [
    event("runtime.turn.queued", { input_text: "Keep working", client_message_id: "initial" }),
    event("runtime.turn.started", {}),
    event("runtime.provider.accepted", { provider_turn_id: "native-turn" }),
    event("runtime.output.delta", { text: "I am still working." }),
  ];

  await page.route(/^http:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.method() === "POST" ? request.postDataJSON() as Record<string, unknown> : {};
    const json = (payload: unknown, status = 200) => route.fulfill({ status, json: payload });
    if (url.pathname === "/api/providers") {
      const provider = {
        provider_id: "codex", label: "Codex", status: "active",
        provider_role: "runtime_engine", kind: "runtime_backend",
      };
      return json({ workspace_id: "default", configured: true, active_provider: provider, items: [provider] });
    }
    if (url.pathname === "/api/apps/widgets/context/steering-fixture") {
      return json({ context: { content: {
        workspace_id: "default", payload: { mode: widgetMode, thread_id: SESSION_ID },
      } } });
    }
    if (url.pathname === "/api/apps/dependencies") return json({ dependencies: [] });
    if (url.pathname === "/api/apps") return json({ items: [] });
    if (url.pathname === "/api/apps/chat/backend" && body.action === "view_filter") {
      return json({ state: { view_filter: { query: "", mode: "thread" } } });
    }
    if (url.pathname === "/api/apps/skills/backend" && body.action === "catalog") return json({ skills: [] });
    if (url.pathname === "/api/inter-agent/runs") return json({ items: [] });
    if (url.pathname === `/api/runtime/sessions/${SESSION_ID}/turns` && request.method() === "POST") {
      submissions.push(body);
      return json({
        session, thread, turn, delivery: "steered",
        events: [event("runtime.message.steered", {
          input_text: body.input_text, client_message_id: body.client_message_id, delivery: "steered",
        }, `steered-${submissions.length}`)],
      }, 202);
    }
    if (url.pathname === `/api/runtime/threads/${SESSION_ID}/read`) return json({ thread, threads: [thread] });
    if (url.pathname === `/api/runtime/threads/${SESSION_ID}`) return json({ thread });
    if (url.pathname === `/api/runtime/sessions/${SESSION_ID}/events`) {
      return json({ revision: "messages-v1", payload: { kind: "messages", data: { messages: [] } } });
    }
    if (url.pathname === "/api/runtime/threads" && url.searchParams.get("projection") === "display") {
      return json({
        revision: "threads-v1", payload: { kind: "threads", data: { threads: [{
          thread_id: SESSION_ID, runtime_session_id: SESSION_ID, title: "Active work",
          source_app_id: "chat", created_at: NOW, updated_at: NOW,
        }] } },
      });
    }
    if (url.pathname === "/api/runtime/threads") return json({ threads: [thread], workspace_id: "default", has_more: false });
    if (url.pathname === `/api/runtime/sessions/${SESSION_ID}/prewarm`) return json(session);
    if (url.pathname === `/api/runtime/turns/${TURN_ID}/client-metrics`) return json({});
    if (url.pathname === "/api/runtime/sessions" && body.prepare_only === true) {
      return json({ ...session, session_id: "unused-prepared-draft" });
    }
    throw new Error(`Unexpected browser request: ${request.method()} ${url.pathname}`);
  });
  await page.routeWebSocket("**/ws/runtime/threads", (socket) => {
    setTimeout(() => socket.send(JSON.stringify({
      type: "runtime.thread.snapshot", workspace_id: "default", threads: [thread], at: NOW,
    })), 0);
  });
  await page.routeWebSocket(`**/ws/runtime/sessions/${SESSION_ID}*`, (socket) => {
    setTimeout(() => socket.send(JSON.stringify({
      type: "runtime.snapshot", session, turns: [turn], events,
      last_event_id: events.at(-1)?.event_id, oldest_event_id: events[0].event_id, has_more_before: false,
    })), 0);
  });
  return submissions;
}

for (const { surface, width, touch, path, widgetMode } of [
  { surface: "app", width: 1280, touch: false, path: "/apps/chat/" },
  { surface: "app", width: 390, touch: false, path: "/apps/chat/" },
  { surface: "app", width: 390, touch: true, path: "/apps/chat/" },
  {
    surface: "floating", width: 480, touch: false, widgetMode: "overlay",
    path: "/apps/chat/widgets/chat-floating/index.html?context=steering-fixture",
  },
  {
    surface: "dock", width: 480, touch: false, widgetMode: "fixed-right",
    path: "/apps/chat/widgets/chat-floating-dock/index.html?context=steering-fixture",
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
