import { describe, expect, it } from "vitest";
import { ChatThread, RuntimeTurn } from "../../api/client";
import { hasActiveRuntimeTurn, withRuntimeAvailability } from "./runtimeStatus";

function thread(overrides: Partial<ChatThread>): ChatThread {
  return {
    thread_id: "thread-1",
    runtime_session_id: "",
    title: "Thread",
    agent_label: "",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-04-21T00:00:00Z",
    updated_at: "2026-04-21T00:00:00Z",
    ...overrides,
  };
}

function turn(status: RuntimeTurn["status"]): RuntimeTurn {
  return {
    turn_id: `turn-${status}`,
    session_id: "session-1",
    workspace_id: "default",
    status,
    input_text: null,
    failure_reason: null,
    created_at: "2026-04-21T00:00:00Z",
    updated_at: "2026-04-21T00:00:00Z",
  };
}

describe("chat sidebar runtime status", () => {
  it("treats queued and active runtime turns as busy", () => {
    expect(hasActiveRuntimeTurn([turn("completed")])).toBe(false);
    expect(hasActiveRuntimeTurn([turn("queued")])).toBe(true);
    expect(hasActiveRuntimeTurn([turn("active")])).toBe(true);
  });

  it("hydrates thread availability from runtime turns", async () => {
    const threads = [thread({ thread_id: "busy", runtime_session_id: "session-1" }), thread({ thread_id: "free", runtime_session_id: "session-2", availability: "busy" })];
    const hydrated = await withRuntimeAvailability(threads, async (sessionId) => ({
      items: sessionId === "session-1" ? [turn("active")] : [turn("completed")],
    }));

    expect(hydrated.find((item) => item.thread_id === "busy")?.availability).toBe("busy");
    expect(hydrated.find((item) => item.thread_id === "free")?.availability).toBe("free");
  });
});
