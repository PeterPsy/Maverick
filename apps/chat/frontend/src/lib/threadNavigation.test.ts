import { describe, expect, it } from "vitest";
import { ChatThread, orderChatThreads } from "../api/client";
import { findThreadByRuntimeSession, upsertOrderedThread } from "./threadNavigation";

function thread(threadId: string, runtimeSessionId: string, overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: threadId,
    runtime_session_id: runtimeSessionId,
    title: "New chat",
    agent_label: "",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "active",
    created_at: "2026-04-19T00:00:00Z",
    updated_at: "2026-04-19T00:00:00Z",
    last_user_message_at: null,
    ...overrides,
  };
}

describe("findThreadByRuntimeSession", () => {
  it("returns the thread already bound to a runtime session", () => {
    expect(findThreadByRuntimeSession([thread("thread-1", "session-1")], "session-1")?.thread_id).toBe("thread-1");
  });

  it("returns null when the session has not been attached to a thread", () => {
    expect(findThreadByRuntimeSession([thread("thread-1", "session-1")], "session-2")).toBeNull();
  });
});

describe("orderChatThreads", () => {
  it("ignores updated_at changes from selection and uses the latest user message", () => {
    const ordered = orderChatThreads([
      thread("selected", "session-selected", {
        created_at: "2026-04-19T09:00:00Z",
        updated_at: "2026-04-19T12:00:00Z",
        last_user_message_at: "2026-04-19T09:30:00Z",
      }),
      thread("latest-user-message", "session-latest", {
        created_at: "2026-04-19T08:00:00Z",
        updated_at: "2026-04-19T10:00:00Z",
        last_user_message_at: "2026-04-19T11:00:00Z",
      }),
    ]);

    expect(ordered.map((item) => item.thread_id)).toEqual(["latest-user-message", "selected"]);
  });
});

describe("upsertOrderedThread", () => {
  it("inserts new threads using chat thread ordering", () => {
    const ordered = upsertOrderedThread(
      [
        thread("older", "session-older", {
          created_at: "2026-04-19T08:00:00Z",
          last_user_message_at: "2026-04-19T08:30:00Z",
        }),
      ],
      thread("newer", "session-newer", {
        created_at: "2026-04-19T09:00:00Z",
        last_user_message_at: "2026-04-19T09:30:00Z",
      }),
    );

    expect(ordered.map((item) => item.thread_id)).toEqual(["newer", "older"]);
  });

  it("merges existing thread updates before ordering", () => {
    const ordered = upsertOrderedThread(
      [
        thread("thread-1", "session-1", {
          title: "Before",
          created_at: "2026-04-19T08:00:00Z",
          last_user_message_at: "2026-04-19T08:30:00Z",
        }),
      ],
      thread("thread-1", "session-1", {
        title: "After",
        created_at: "2026-04-19T08:00:00Z",
        last_user_message_at: "2026-04-19T10:30:00Z",
      }),
    );

    expect(ordered).toHaveLength(1);
    expect(ordered[0].title).toBe("After");
    expect(ordered[0].last_user_message_at).toBe("2026-04-19T10:30:00Z");
  });
});
