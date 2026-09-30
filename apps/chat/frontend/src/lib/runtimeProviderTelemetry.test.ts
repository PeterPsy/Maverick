import { beforeEach, describe, expect, it } from "vitest";
import type { RuntimeEvent, RuntimeTurn } from "../api/client";
import { runtimeActivityLabel } from "./runtimeActivity";
import { latestRuntimeStepLabel, runtimeStepLabel } from "./runtimeStepLabels";
import { clearTranscriptProjectionCache, eventsToMessages } from "./transcript";

function event(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    event_id: "account-update",
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.step.updated",
    payload: {
      label: "account updated",
      provider_event_type: "account.updated",
      raw: { type: "account.updated", item: { authMode: "chatgpt", planType: "pro" } },
    },
    created_at: "2026-09-30T11:01:41.000Z",
    ...overrides,
  };
}

describe("provider account telemetry", () => {
  beforeEach(clearTranscriptProjectionCache);

  it.each(["account.updated", "account/updated", "account_updated", "account updated"])(
    "omits persisted %s updates from transcript cards and activity labels",
    (providerEventType) => {
      const telemetry = event({ payload: { label: "Provider account refreshed", provider_event_type: providerEventType } });

      expect(eventsToMessages([telemetry])).toEqual([]);
      expect(runtimeStepLabel(telemetry)).toBeNull();
    },
  );

  it("hides the screenshot payload and label-only history without splitting tool groups", () => {
    const messages = eventsToMessages([
      event({ event_id: "tool-1", event_type: "runtime.tool_call.completed", payload: { name: "command", command: "pwd" } }),
      event({}),
      event({ event_id: "account-label", payload: { label: "account updated" } }),
      event({ event_id: "tool-2", event_type: "runtime.tool_call.completed", payload: { name: "command", command: "git status -sb" } }),
      event({ event_id: "answer", event_type: "runtime.output.delta", payload: { text: "Files checked." } }),
    ]);

    expect(messages).toMatchObject([
      { role: "tool", toolCalls: [{ id: "tool-1" }, { id: "tool-2" }] },
      { role: "agent", content: "Files checked." },
    ]);
    expect(messages).toHaveLength(2);
  });

  it("keeps account telemetry from replacing the active work label", () => {
    const work = event({ event_id: "work", payload: { label: "Reading workspace" } });
    const activeTurn: RuntimeTurn = {
      turn_id: "turn-1",
      session_id: "session-1",
      workspace_id: "default",
      status: "active",
      input_text: "Check files",
      failure_reason: null,
      created_at: "2026-09-30T11:01:40.000Z",
      updated_at: "2026-09-30T11:01:41.000Z",
    };

    expect(latestRuntimeStepLabel([work, event({})])).toBe("Reading workspace");
    expect(runtimeActivityLabel({ activeTurn, events: [work, event({})], isRuntimeBusy: true })).toBe("Reading workspace");
    expect(runtimeActivityLabel({ activeTurn, events: [event({})], isRuntimeBusy: true })).toBe("Thinking");
  });

  it("preserves meaningful unknown notifications and assistant account mentions", () => {
    const messages = eventsToMessages([
      event({ event_id: "future", payload: { label: "future capability updated", provider_event_type: "future.capability.updated" } }),
      event({ event_id: "answer", event_type: "runtime.output.delta", payload: { text: "The account updated successfully." } }),
    ]);

    expect(messages).toMatchObject([
      { role: "step", step: { label: "future capability updated" } },
      { role: "agent", content: "The account updated successfully." },
    ]);
  });
});
