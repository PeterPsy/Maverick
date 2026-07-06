import { describe, expect, it } from "vitest";
import type { RuntimeEvent } from "../api/client";
import type { PendingMessage } from "../lib/messageState";
import { eventsToMessages } from "../lib/transcript";
import { visibleChatMessages, visibleProjectionEvents } from "./useChatControllerPresentation";

function runtimeEvent(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    event_id: "event-1",
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.output.delta",
    payload: {},
    created_at: isoAt(0),
    ...overrides,
  };
}

function delta(index: number, text = `chunk-${index} `): RuntimeEvent {
  return runtimeEvent({
    event_id: `delta-${index}`,
    event_type: "runtime.output.delta",
    payload: { text },
    created_at: isoAt(index + 1),
  });
}

function isoAt(secondOffset: number): string {
  return new Date(Date.UTC(2026, 3, 19, 0, 0, secondOffset)).toISOString();
}

describe("chat controller presentation message projection", () => {
  it("keeps the full turn when the event window would otherwise start mid-turn", () => {
    const events = [
      runtimeEvent({
        event_id: "queued",
        event_type: "runtime.turn.queued",
        payload: { input_text: "work", client_message_id: "client-message-1" },
      }),
      ...Array.from({ length: 501 }, (_, index) => delta(index)),
    ];

    const projected = visibleProjectionEvents(events, 1);

    expect(projected[0].event_id).toBe("queued");
    expect(projected).toHaveLength(events.length);
  });

  it("does not append a stale pending message when full events already confirm it", () => {
    const pending: PendingMessage = {
      clientMessageId: "client-confirmed",
      content: "already sent",
      createdAt: "2026-04-19T00:00:00.000Z",
      attachments: [],
      appReferences: [],
    };
    const events = [
      runtimeEvent({
        event_id: "old-queued",
        turn_id: "old-turn",
        event_type: "runtime.turn.queued",
        payload: { input_text: "already sent", client_message_id: "client-confirmed" },
      }),
      ...Array.from({ length: 501 }, (_, index) =>
        runtimeEvent({
          event_id: `later-step-${index}`,
          turn_id: `later-turn-${index}`,
          event_type: "runtime.step.updated",
          payload: { label: `step ${index}` },
          created_at: isoAt(1000 + index),
        }),
      ),
    ];

    const result = visibleChatMessages(events, [pending], [], 1);

    expect(result.messages.some((message) => message.id === "client-confirmed" && message.status === "pending")).toBe(false);
  });

  it("prevents complete final text from replacing a long streamed turn as a duplicate final bubble", () => {
    const chunks = Array.from({ length: 501 }, (_, index) => `chunk-${index} `);
    const completeText = chunks.join("");
    const events = [
      runtimeEvent({
        event_id: "queued",
        event_type: "runtime.turn.queued",
        payload: { input_text: "stream a long answer", client_message_id: "client-long" },
      }),
      ...chunks.map((text, index) => delta(index, text)),
      runtimeEvent({
        event_id: "final",
        event_type: "runtime.output.final",
        payload: { text: "", complete_text: completeText },
        created_at: isoAt(2000),
      }),
    ];

    const messages = eventsToMessages(visibleProjectionEvents(events, 1));
    const agentMessages = messages.filter((message) => message.role === "agent");

    expect(agentMessages).toHaveLength(1);
    expect(agentMessages[0]).toMatchObject({ id: "turn-1:agent:stream:0", content: completeText, status: "complete" });
  });
});
