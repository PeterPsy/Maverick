import { describe, expect, it } from "vitest";
import type { ChatThread, RuntimeEvent } from "../../api/client";
import { indexTranscriptSearchText, threadsNeedingTranscriptIndex, type TranscriptSearchCache } from "./transcriptSearchIndex";

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    agent_label: "",
    agent_role_id: "",
    agent_type_id: "",
    archived: false,
    availability: "free",
    created_at: "2026-05-21T00:00:00Z",
    last_completed_response_at: null,
    last_user_message_at: null,
    project_id: null,
    runtime_session_id: "session-1",
    source_app_id: "chat",
    system_prompt: "",
    thread_id: "thread-1",
    title: "Budget notes",
    updated_at: "2026-05-21T00:00:00Z",
    ...overrides,
  };
}

function event(sessionId: string, text: string): RuntimeEvent {
  return {
    event_id: `${sessionId}:event`,
    session_id: sessionId,
    turn_id: `${sessionId}:turn`,
    event_type: "runtime.turn.queued",
    payload: { input_text: text },
    created_at: "2026-05-21T00:00:00Z",
  };
}

describe("transcript search indexing", () => {
  it("bounds concurrent transcript event loads and publishes progress", async () => {
    const threads = Array.from({ length: 7 }, (_, index) =>
      thread({
        runtime_session_id: `session-${index}`,
        thread_id: `thread-${index}`,
      }),
    );
    const cache: TranscriptSearchCache = new Map();
    const controller = new AbortController();
    let activeLoads = 0;
    let maxActiveLoads = 0;
    const progressSnapshots: number[] = [];

    const snapshot = await indexTranscriptSearchText({
      allThreads: threads,
      cache,
      eventLimit: 500,
      loadEvents: async (sessionId) => {
        activeLoads += 1;
        maxActiveLoads = Math.max(maxActiveLoads, activeLoads);
        await new Promise((resolve) => setTimeout(resolve, 1));
        activeLoads -= 1;
        return { items: [event(sessionId, `message from ${sessionId}`)] };
      },
      maxConcurrent: 3,
      onProgress: (progress) => progressSnapshots.push(Object.keys(progress).length),
      signal: controller.signal,
      threadsToIndex: threadsNeedingTranscriptIndex(threads, cache),
    });

    expect(maxActiveLoads).toBeLessThanOrEqual(3);
    expect(Object.keys(snapshot)).toHaveLength(7);
    expect(snapshot["thread-6"]).toContain("message from session-6");
    expect(progressSnapshots.at(-1)).toBe(7);
  });
});
