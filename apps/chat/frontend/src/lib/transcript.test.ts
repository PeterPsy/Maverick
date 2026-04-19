import { describe, expect, it } from "vitest";
import type { RuntimeEvent } from "../api/client";
import { eventsToMessages } from "./transcript";

function event(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    event_id: "event-1",
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.turn.queued",
    payload: {},
    created_at: "2026-04-19T00:00:00.000Z",
    ...overrides,
  };
}

describe("runtime event transcript projection", () => {
  it("projects one human message from a queued runtime turn", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.queued",
        payload: { input_text: "hello", client_message_id: "client-message-1" },
      }),
    ]);
    expect(messages).toMatchObject([{ id: "client-message-1", role: "human", content: "hello", status: "complete" }]);
  });

  it("projects final provider output as an agent message", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.output.final",
        payload: { text: "## Result" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "agent", content: "## Result", status: "complete" }]);
  });

  it("projects cancelled turns as system messages", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.cancelled",
        payload: { reason: "interrupted_by_user" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "system", content: "interrupted_by_user", status: "failed" }]);
  });
});
