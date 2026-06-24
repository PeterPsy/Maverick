import { describe, expect, it } from "vitest";
import type { ChatProject, ChatThread } from "../../api/client";
import { buildSections, filterThreadsBySource, isThreadBusy, isThreadUnread, threadSourceBadgeLabel } from "./sections";

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: "thread-1",
    runtime_session_id: "session-1",
    title: "Chat",
    agent_label: "",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-04-19T00:00:00.000Z",
    updated_at: "2026-04-19T00:00:01.000Z",
    last_user_message_at: null,
    ...overrides,
  };
}

function project(overrides: Partial<ChatProject> = {}): ChatProject {
  return {
    project_id: "project-1",
    name: "Client",
    created_at: "2026-04-19T00:00:00.000Z",
    updated_at: "2026-04-19T00:00:01.000Z",
    ...overrides,
  };
}

describe("chat sidebar runtime status", () => {
  it("groups threads without replacing the websocket-provided order", () => {
    const sections = buildSections([], [
      thread({ thread_id: "first", title: "First" }),
      thread({ thread_id: "second", title: "Second" }),
    ]);

    expect(sections[0].items.map((item) => item.thread_id)).toEqual(["first", "second"]);
  });

  it("keeps project-assigned threads out of No project while project names are still loading", () => {
    const sections = buildSections([], [
      thread({ thread_id: "assigned", project_id: "project-1" }),
      thread({ thread_id: "unassigned", project_id: null }),
    ]);

    expect(sections.map((section) => section.id)).toEqual(["unassigned", "project:project-1"]);
    expect(sections[0].items.map((item) => item.thread_id)).toEqual(["unassigned"]);
    expect(sections[1].items.map((item) => item.thread_id)).toEqual(["assigned"]);
    expect(sections[1].canManage).toBe(false);
  });

  it("reuses loaded project names for project sections", () => {
    const sections = buildSections([project({ project_id: "project-1", name: "Client" })], [
      thread({ thread_id: "assigned", project_id: "project-1" }),
    ]);

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({ id: "project-1", title: "Client", canManage: true });
    expect(sections[0].items.map((item) => item.thread_id)).toEqual(["assigned"]);
  });

  it("filters Senses threads for the Occhiali view", () => {
    const chatThread = thread({ thread_id: "chat-thread", source_app_id: "chat" });
    const sensesThread = thread({ thread_id: "senses-thread", source_app_id: "senses" });

    expect(filterThreadsBySource([chatThread, sensesThread], "senses").map((item) => item.thread_id)).toEqual(["senses-thread"]);
    expect(buildSections([], [chatThread, sensesThread], "senses")[0].items.map((item) => item.thread_id)).toEqual(["senses-thread"]);
  });

  it("labels Senses threads as Occhiali", () => {
    expect(threadSourceBadgeLabel(thread({ source_app_id: "senses" }))).toBe("Occhiali");
    expect(threadSourceBadgeLabel(thread({ source_app_id: "chat" }))).toBeNull();
  });

  it("uses the runtime thread availability supplied over websocket", () => {
    expect(isThreadBusy(thread({ availability: "busy" }))).toBe(true);
    expect(isThreadBusy(thread({ availability: "queued" }))).toBe(true);
    expect(isThreadBusy(thread({ availability: "active" }))).toBe(true);
    expect(isThreadBusy(thread({ availability: "free" }))).toBe(false);
  });

  it("marks completed unread responses only when the thread is not busy", () => {
    expect(isThreadUnread(thread({ availability: "free", has_unread_completed_response: true }))).toBe(true);
    expect(isThreadUnread(thread({ availability: "active", has_unread_completed_response: true }))).toBe(false);
    expect(isThreadUnread(thread({ availability: "free", has_unread_completed_response: false }))).toBe(false);
  });
});
