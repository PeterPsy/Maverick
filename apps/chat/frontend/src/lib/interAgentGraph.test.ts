import { describe, expect, it } from "vitest";
import type { InterAgentEventRecord } from "../api/client";
import { eventSummary } from "./interAgentGraph";

function event(payload: Record<string, unknown>): InterAgentEventRecord {
  return {
    event_id: "event-1",
    workspace_id: "default",
    run_id: "run-1",
    thread_id: "thread-1",
    root_runtime_session_id: "session-1",
    participant_id: "orchestrator",
    runtime_session_id: null,
    runtime_turn_id: null,
    runtime_event_id: null,
    event_type: "inter_agent.summary.updated",
    visibility_plane: "summary",
    sequence: 1,
    correlation_id: "event-1",
    idempotency_key: "event-1",
    payload,
    created_at: "2026-06-18T10:00:00Z",
  };
}

describe("interAgentGraph", () => {
  it("prefers final_answer over legacy summary payload text", () => {
    expect(
      eventSummary(
        event({
          final_answer: "Final answer ready for the user.",
          summary: "Multi-agent run completed. Implementer: Draft. Reviewer: Final answer.",
        }),
      ),
    ).toBe("Final answer ready for the user.");
  });
});
