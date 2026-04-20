import { describe, expect, it } from "vitest";
import { ChatThread } from "../api/client";
import { findThreadByRuntimeSession } from "./threadNavigation";

function thread(threadId: string, runtimeSessionId: string): ChatThread {
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
