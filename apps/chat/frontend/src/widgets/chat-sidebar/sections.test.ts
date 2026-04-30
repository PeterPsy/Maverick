import { describe, expect, it } from "vitest";
import type { ChatThread } from "../../api/client";
import { buildSections, isThreadBusy } from "./sections";

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

  it("uses the runtime thread availability supplied over websocket", () => {
    expect(isThreadBusy(thread({ availability: "busy" }))).toBe(true);
    expect(isThreadBusy(thread({ availability: "queued" }))).toBe(true);
    expect(isThreadBusy(thread({ availability: "active" }))).toBe(true);
    expect(isThreadBusy(thread({ availability: "free" }))).toBe(false);
  });
});
