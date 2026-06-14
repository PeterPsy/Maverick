import { describe, expect, it } from "vitest";
import type { ChatThread, RuntimeTurn } from "../api/client";
import { isActiveRuntimeTurnBusyForThread } from "./useChatAppController";

function thread(availability: string): ChatThread {
  return {
    thread_id: "thread-1",
    runtime_session_id: "session-1",
    title: "Thread",
    agent_label: "chat",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability,
    created_at: "2026-04-19T10:00:00Z",
    updated_at: "2026-04-19T10:00:00Z",
  };
}

function turn(status: string): RuntimeTurn {
  return {
    turn_id: "turn-1",
    session_id: "session-1",
    workspace_id: "default",
    status,
    input_text: "work",
    failure_reason: null,
    created_at: "2026-04-19T10:00:00Z",
    updated_at: "2026-04-19T10:00:01Z",
  };
}

describe("chat runtime busy guard", () => {
  it("treats active turns as busy only while the selected thread is busy", () => {
    expect(isActiveRuntimeTurnBusyForThread(turn("active"), thread("active"))).toBe(true);
    expect(isActiveRuntimeTurnBusyForThread(turn("queued"), thread("queued"))).toBe(true);
    expect(isActiveRuntimeTurnBusyForThread(turn("active"), thread("free"))).toBe(false);
  });

  it("does not treat terminal turns as busy", () => {
    expect(isActiveRuntimeTurnBusyForThread(turn("completed"), thread("active"))).toBe(false);
    expect(isActiveRuntimeTurnBusyForThread(turn("failed"), thread("busy"))).toBe(false);
  });

  it("keeps existing busy behavior when the thread is not selected yet", () => {
    expect(isActiveRuntimeTurnBusyForThread(turn("active"), null)).toBe(true);
  });
});
