import { describe, expect, it } from "vitest";
import type { ChatThread, RuntimeTurn } from "../api/client";
import type { RuntimeTranscriptCacheEntry } from "../lib/runtimeTranscriptCache";
import { selectCachedActiveTurnForThread } from "./useRuntimeTranscriptCache";

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

function cacheEntry(activeTurn: RuntimeTurn | null): RuntimeTranscriptCacheEntry {
  return {
    activeSession: null,
    activeTurn,
    events: [],
    hasLoadedHistory: true,
    hasMoreHistory: false,
  };
}

describe("runtime transcript cache selection", () => {
  it("does not resurrect terminal cached turns for busy threads", () => {
    expect(selectCachedActiveTurnForThread(thread("active"), cacheEntry(turn("completed")))).toBeNull();
    expect(selectCachedActiveTurnForThread(thread("queued"), cacheEntry(turn("cancelled")))).toBeNull();
  });

  it("reuses only genuinely busy cached turns for busy threads", () => {
    const activeTurn = turn("active");

    expect(selectCachedActiveTurnForThread(thread("active"), cacheEntry(activeTurn))).toBe(activeTurn);
    expect(selectCachedActiveTurnForThread(thread("free"), cacheEntry(activeTurn))).toBeNull();
  });
});
