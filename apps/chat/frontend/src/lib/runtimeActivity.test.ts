import { describe, expect, it } from "vitest";
import type { RuntimeEvent, RuntimeTurn } from "../api/client";
import { runtimeActivityLabel } from "./runtimeActivity";

function event(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    event_id: "event-1",
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.turn.started",
    payload: {},
    created_at: "2026-06-19T00:00:00.000Z",
    ...overrides,
  };
}

function turn(status: string, overrides: Partial<RuntimeTurn> = {}): RuntimeTurn {
  return {
    turn_id: "turn-1",
    session_id: "session-1",
    workspace_id: "default",
    status,
    input_text: "Please inspect the repo.",
    failure_reason: null,
    created_at: "2026-06-19T00:00:00.000Z",
    updated_at: "2026-06-19T00:00:01.000Z",
    ...overrides,
  };
}

describe("runtimeActivityLabel", () => {
  it("uses submit and loading states before runtime activity", () => {
    expect(runtimeActivityLabel({ events: [], isRuntimeBusy: false, isSending: true })).toBe("Starting");
    expect(runtimeActivityLabel({ events: [], isBootstrapping: true, isRuntimeBusy: true, isSending: true })).toBe("Loading chat");
    expect(runtimeActivityLabel({ events: [], isHistoryLoading: true, isRuntimeBusy: true, isSending: true })).toBe("Loading history");
  });

  it("shows queued instead of thinking while the turn waits to start", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("queued"),
        events: [event({ event_type: "runtime.turn.queued", payload: { input_text: "work" } })],
        isRuntimeBusy: true,
      }),
    ).toBe("Queued");
  });

  it("shows thinking only for an active turn without a more specific activity", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active"),
        events: [event({ event_type: "runtime.turn.started" })],
        isRuntimeBusy: true,
      }),
    ).toBe("Thinking");
  });

  it("uses the latest visible step for the active turn", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active"),
        events: [
          event({ event_id: "old-step", turn_id: "turn-old", event_type: "runtime.step.updated", payload: { label: "Old work" } }),
          event({ event_id: "step", event_type: "runtime.step.updated", payload: { label: "Reading workspace" } }),
        ],
        isRuntimeBusy: true,
      }),
    ).toBe("Reading workspace");
  });

  it("shows writing while assistant output is streaming", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active"),
        events: [event({ event_type: "runtime.output.delta", payload: { text: "Drafting" } })],
        isRuntimeBusy: true,
      }),
    ).toBe("Writing");
  });

  it("shows active tool work instead of thinking", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active"),
        events: [
          event({
            event_type: "runtime.tool_call.started",
            payload: { name: "web_search", tool_kind: "web_search", status: "started" },
          }),
        ],
        isRuntimeBusy: true,
      }),
    ).toBe("Searching web");
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active"),
        events: [
          event({
            event_type: "runtime.tool_call.updated",
            payload: { name: "command", tool_kind: "command", command: "sed -n '1,80p' apps/chat/frontend/src/App.tsx" },
          }),
        ],
        isRuntimeBusy: true,
      }),
    ).toBe("Reading files");
  });

  it("returns to thinking after a tool completes and the model has control again", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active"),
        events: [
          event({
            event_type: "runtime.tool_call.completed",
            payload: { name: "command", tool_kind: "command", command: "npm test", status: "completed" },
          }),
        ],
        isRuntimeBusy: true,
      }),
    ).toBe("Thinking");
  });

  it("does not show stale activity from another turn", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: turn("active", { turn_id: "turn-2" }),
        events: [
          event({ event_id: "old-output", turn_id: "turn-1", event_type: "runtime.output.delta", payload: { text: "Old output" } }),
          event({ event_id: "new-start", turn_id: "turn-2", event_type: "runtime.turn.started" }),
        ],
        isRuntimeBusy: true,
      }),
    ).toBe("Thinking");
  });

  it("does not infer activity from old events when no active turn is known", () => {
    expect(
      runtimeActivityLabel({
        activeTurn: null,
        events: [event({ event_type: "runtime.output.delta", payload: { text: "Old output" } })],
        isRuntimeBusy: true,
      }),
    ).toBe("");
  });
});
