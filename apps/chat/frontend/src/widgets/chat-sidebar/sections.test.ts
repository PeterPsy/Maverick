import { describe, expect, it } from "vitest";
import type { ChatProject, ChatThread } from "../../api/client";
import { buildSections, filterThreads, filterThreadsForSidebar, isThreadBusy, isThreadUnread, threadSourceBadges } from "./sections";

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

  it("filters Senses threads for the Senses view", () => {
    const chatThread = thread({ thread_id: "chat-thread", source_app_id: "chat" });
    const sensesThread = thread({ thread_id: "senses-thread", source_app_id: "senses" });

    expect(filterThreads([chatThread, sensesThread], "senses").map((item) => item.thread_id)).toEqual(["senses-thread"]);
    expect(buildSections([], [chatThread, sensesThread], "senses")[0].items.map((item) => item.thread_id)).toEqual(["senses-thread"]);
  });

  it("filters multi-agent threads for the Multi view", () => {
    const chatThread = thread({ thread_id: "chat-thread", runtime_session_id: "chat-session" });
    const multiThread = thread({ thread_id: "multi-thread", runtime_session_id: "multi-session" });
    const multiAgentThreadIds = new Set(["multi-thread"]);

    expect(filterThreads([chatThread, multiThread], "multi_agent", multiAgentThreadIds).map((item) => item.thread_id)).toEqual([
      "multi-thread",
    ]);
    expect(buildSections([], [chatThread, multiThread], "multi_agent", multiAgentThreadIds)[0].items.map((item) => item.thread_id)).toEqual([
      "multi-thread",
    ]);
  });

  it("filters unread and in-progress chats for the Unread view", () => {
    const readThread = thread({ thread_id: "read-thread", has_unread_completed_response: false });
    const unreadThread = thread({ thread_id: "unread-thread", has_unread_completed_response: true });
    const queuedThread = thread({ thread_id: "queued-thread", availability: "queued" });
    const activeThread = thread({ thread_id: "active-thread", availability: "active" });
    const busyThread = thread({ thread_id: "busy-thread", availability: "busy" });

    const threads = [readThread, unreadThread, queuedThread, activeThread, busyThread];
    const expectedThreadIds = ["unread-thread", "queued-thread", "active-thread", "busy-thread"];

    expect(filterThreads(threads, "unread").map((item) => item.thread_id)).toEqual(expectedThreadIds);
    expect(buildSections([], threads, "unread")[0].items.map((item) => item.thread_id)).toEqual(expectedThreadIds);
  });

  it("retains only the selected read chat while browsing the Unread view", () => {
    const firstReadThread = thread({ thread_id: "first-thread", has_unread_completed_response: false });
    const secondUnreadThread = thread({ thread_id: "second-thread", has_unread_completed_response: true });

    expect(
      filterThreadsForSidebar([firstReadThread, secondUnreadThread], "unread", new Set(), "first-thread").map(
        (item) => item.thread_id,
      ),
    ).toEqual(["first-thread", "second-thread"]);
    expect(buildSections([], [firstReadThread, secondUnreadThread], "unread", new Set(), "first-thread")[0].items).toEqual([
      firstReadThread,
      secondUnreadThread,
    ]);

    const secondReadThread = { ...secondUnreadThread, has_unread_completed_response: false };
    expect(
      filterThreadsForSidebar([firstReadThread, secondReadThread], "unread", new Set(), "second-thread").map(
        (item) => item.thread_id,
      ),
    ).toEqual(["second-thread"]);
  });

  it("hides project sections without matching chats while a filter is active", () => {
    const sections = buildSections(
      [
        project({ project_id: "senses-project", name: "Senses project" }),
        project({ project_id: "chat-project", name: "Chat project" }),
        project({ project_id: "empty-project", name: "Empty project" }),
      ],
      [
        thread({ thread_id: "senses-thread", project_id: "senses-project", source_app_id: "senses" }),
        thread({ thread_id: "chat-thread", project_id: "chat-project", source_app_id: "chat" }),
        thread({ thread_id: "unassigned-chat", project_id: null, source_app_id: "chat" }),
      ],
      "senses",
    );

    expect(sections.map((section) => section.id)).toEqual(["senses-project"]);
    expect(sections[0].items.map((item) => item.thread_id)).toEqual(["senses-thread"]);
  });

  it("returns no project sections when an active filter has no matching chats", () => {
    expect(buildSections([project({ project_id: "empty-project" })], [], "unread")).toEqual([]);
  });

  it("keeps empty project sections visible in the All view", () => {
    const sections = buildSections([project({ project_id: "empty-project" })], []);

    expect(sections.map((section) => section.id)).toEqual(["empty-project"]);
    expect(sections[0].items).toEqual([]);
  });

  it("returns source badge metadata for Senses and multi-agent threads", () => {
    const multiAgentThreadIds = new Set(["multi-thread"]);

    expect(threadSourceBadges(thread({ source_app_id: "senses" }))).toEqual([{ icon: "sensors", kind: "senses", label: "Senses" }]);
    expect(threadSourceBadges(thread({ thread_id: "multi-thread" }), multiAgentThreadIds)).toEqual([
      { icon: "account_tree", kind: "multi_agent", label: "Multi-chat" },
    ]);
    expect(threadSourceBadges(thread({ source_app_id: "chat" }))).toEqual([]);
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
