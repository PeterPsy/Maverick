import type { Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

export const SESSION_ID = "session-steering-browser";
export const TURN_ID = "turn-still-working";
const NOW = "2026-09-06T00:00:00.000Z";

export async function installActiveTurn(page: Page, widgetMode = "overlay", mutations: Record<string, unknown>[] = [], threadProjectId: string | null = null) {
  await page.route("**/material-symbols-rounded.woff2", (route) => route.fulfill({
    path: fileURLToPath(new URL("../../../../base-shell/frontend/public/material-symbols-rounded.woff2", import.meta.url)),
    contentType: "font/woff2",
  }));
  const submissions: Record<string, unknown>[] = [];
  const session = {
    session_id: SESSION_ID, workspace_id: "default", agent_id: "chat",
    source_app_id: "chat", status: "running", effective_mode: "sandbox",
  };
  const thread = {
    thread_id: SESSION_ID, runtime_session_id: SESSION_ID, title: "Active work",
    source_app_id: "chat", agent_label: "Chat", agent_type_id: "", agent_role_id: "",
    system_prompt: "", project_id: threadProjectId, archived: false, availability: "active",
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
  const projects = [{ project_id: "project-demo", name: "Demo", created_at: NOW, updated_at: NOW }];

  await page.route(/^http:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const body = ["POST", "PATCH"].includes(request.method()) ? request.postDataJSON() as Record<string, unknown> : {};
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
    if (url.pathname === "/api/apps/chat/backend" && body.action === "pwa.read_model") {
      return json({ revision: "projects-v1", payload: { kind: "projects", data: { projects, has_more: false } } });
    }
    if (url.pathname === "/api/apps/chat/backend" && body.action === "projects.list") return json({ projects });
    if (url.pathname === "/api/apps/chat/backend" && body.action === "projects.create") {
      const project = { project_id: "new-project", name: String(body.name), created_at: NOW, updated_at: NOW };
      projects.push(project);
      mutations.push({ ...body, action: "project-create" });
      return json({ project, projects });
    }
    if (url.pathname === "/api/apps/chat/backend" && body.action === "projects.update") {
      const project = projects.find((item) => item.project_id === body.project_id)!;
      project.name = String(body.name);
      mutations.push({ ...body, action: "project-rename" });
      return json({ project, projects });
    }
    if (url.pathname === "/api/apps/chat/backend" && body.action === "projects.delete") {
      const index = projects.findIndex((item) => item.project_id === body.project_id);
      if (index >= 0) projects.splice(index, 1);
      const deleted = thread.project_id === body.project_id ? [SESSION_ID] : [];
      mutations.push({ ...body, action: "project-delete" });
      return json({ projects, threads: deleted.length ? [] : [thread], deleted_thread_ids: deleted });
    }
    if (url.pathname === "/api/apps/chat/backend" && body.action === "scheduled.list") return json({ chats: [] });
    if (url.pathname === "/api/apps") return json({ items: [] });
    if (url.pathname === "/api/apps/chat/backend" && ["view_filter", "set_view_filter"].includes(String(body.action))) {
      return json({ state: { view_filter: { query: body.query || "", mode: "thread" } } });
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
    if (url.pathname === "/api/runtime/threads/delete-batch") {
      const ids = body.thread_ids as string[];
      mutations.push({ action: "delete-batch", thread_ids: ids });
      return json({ deleted_thread_ids: ids, deleted_runtime_session_ids: [SESSION_ID],
        results: ids.map((thread_id) => ({ thread_id, status: "deleted" })) });
    }
    if (url.pathname === `/api/runtime/threads/${SESSION_ID}`) {
      if (request.method() === "PATCH") {
        mutations.push({ action: "rename", ...body });
        return json({ thread: { ...thread, title: body.title, project_id: body.project_id } });
      }
      if (request.method() === "DELETE") {
        mutations.push({ action: "delete", thread_id: SESSION_ID });
        return json({ threads: [], deleted_thread_ids: [SESSION_ID], deleted_runtime_session_ids: [SESSION_ID] });
      }
      return json({ thread });
    }
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
