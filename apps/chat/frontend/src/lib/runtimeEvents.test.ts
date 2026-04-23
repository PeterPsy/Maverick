import { describe, expect, it, vi } from "vitest";
import type { RuntimeEvent, RuntimeWebSocketFrame } from "../api/client";
import { runtimeEventFromWebSocketFrame, runtimeWebSocketUrl } from "../api/client";
import { isTransientReplayError } from "../hooks/useRuntimeEvents";
import { inferActiveRuntimeTurn, lastRuntimeEventId, mergeRuntimeEvents } from "./runtimeEvents";
import { isNoisyRuntimeLabel, latestRuntimeStepLabel, runtimeStepLabel } from "./runtimeStepLabels";

function event(event_id: string, created_at: string): RuntimeEvent {
  return {
    event_id,
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.output.delta",
    payload: {},
    created_at,
  };
}

describe("runtime websocket helpers", () => {
  it("builds a same-origin websocket URL with replay cursor", () => {
    vi.stubGlobal("window", { location: { protocol: "https:", host: "example.localhost" } });

    expect(runtimeWebSocketUrl("session 1", "event-1")).toBe(
      "wss://example.localhost/ws/runtime/sessions/session%201?last_event_id=event-1",
    );

    vi.unstubAllGlobals();
  });

  it("extracts runtime events and ignores transport frames", () => {
    const runtimeFrame: RuntimeWebSocketFrame = { type: "runtime.event", event: event("event-1", "2026-04-19T10:00:00Z") };
    const heartbeatFrame: RuntimeWebSocketFrame = { type: "runtime.heartbeat", session_id: "session-1", at: "2026-04-19T10:00:00Z" };

    expect(runtimeEventFromWebSocketFrame(runtimeFrame)?.event_id).toBe("event-1");
    expect(runtimeEventFromWebSocketFrame(heartbeatFrame)).toBeNull();
  });

  it("deduplicates and orders runtime events from HTTP replay and WebSocket", () => {
    const merged = mergeRuntimeEvents(
      [event("event-2", "2026-04-19T10:00:01Z")],
      [event("event-1", "2026-04-19T10:00:00Z"), event("event-2", "2026-04-19T10:00:01Z")],
    );

    expect(merged.map((item) => item.event_id)).toEqual(["event-1", "event-2"]);
    expect(lastRuntimeEventId(merged)).toBe("event-2");
  });

  it("infers an active turn from persisted runtime events after refresh", () => {
    const activeTurn = inferActiveRuntimeTurn(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("started", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.started" },
      ],
      "session-1",
    );

    expect(activeTurn).toMatchObject({ turn_id: "turn-1", session_id: "session-1", status: "active", input_text: "work" });
  });

  it("does not infer a completed turn as active after refresh", () => {
    const activeTurn = inferActiveRuntimeTurn(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("completed", "2026-04-19T10:00:02Z"), event_type: "runtime.turn.completed" },
      ],
      "session-1",
    );

    expect(activeTurn).toBeNull();
  });

  it("treats final runtime output as terminal when a completed event is missing", () => {
    const activeTurn = inferActiveRuntimeTurn(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("started", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.started" },
        { ...event("final", "2026-04-19T10:00:02Z"), event_type: "runtime.output.final", payload: { text: "done" } },
      ],
      "session-1",
    );

    expect(activeTurn).toBeNull();
  });

  it("does not let a late started event reactivate a terminal turn", () => {
    const activeTurn = inferActiveRuntimeTurn(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("final", "2026-04-19T10:00:01Z"), event_type: "runtime.output.final", payload: { text: "done" } },
        { ...event("started", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.started" },
      ],
      "session-1",
    );

    expect(activeTurn).toBeNull();
  });

  it("treats session-level terminal runtime events as closing the latest active turn", () => {
    const activeTurn = inferActiveRuntimeTurn(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("started", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.started" },
        {
          ...event("failed", "2026-04-19T10:00:02Z"),
          turn_id: "",
          event_type: "runtime.turn.failed",
          payload: { error: "Codex app-server error" },
        },
      ],
      "session-1",
    );

    expect(activeTurn).toBeNull();
  });

  it("scopes live runtime labels to the current active turn", () => {
    const oldStep = {
      ...event("old-step", "2026-04-19T10:00:00Z"),
      turn_id: "turn-1",
      event_type: "runtime.step.updated",
      payload: { label: "Codex app-server error" },
    };
    const newTurn = {
      ...event("new-turn", "2026-04-19T10:00:01Z"),
      turn_id: "turn-2",
      event_type: "runtime.turn.started",
      payload: {},
    };

    expect(latestRuntimeStepLabel([oldStep, newTurn], "turn-2")).toBe("");
    expect(latestRuntimeStepLabel([oldStep, newTurn], "turn-1")).toBe("Codex app-server error");
  });

  it("classifies transient runtime replay failures", () => {
    expect(isTransientReplayError(new Error("Request failed 502: /api/runtime/sessions/session-1/events"))).toBe(true);
    expect(isTransientReplayError(new Error("Request failed 404: /api/runtime/sessions/session-1/events"))).toBe(false);
  });

  it("filters provider stdin prompts from live runtime labels", () => {
    const noisy = {
      ...event("stdin", "2026-04-19T10:00:00Z"),
      event_type: "runtime.step.updated",
      payload: { label: "Reading additional input from stdin..." },
    };
    const visible = {
      ...event("visible", "2026-04-19T10:00:01Z"),
      event_type: "runtime.step.updated",
      payload: { label: "Reading workspace" },
    };

    expect(isNoisyRuntimeLabel("Reading additional input from stdin...")).toBe(true);
    expect(isNoisyRuntimeLabel("Reading additional input from stdin…")).toBe(true);
    expect(runtimeStepLabel(noisy)).toBeNull();
    expect(latestRuntimeStepLabel([visible, noisy])).toBe("Reading workspace");
  });

  it("filters provider telemetry from live runtime labels", () => {
    const rateLimits = {
      ...event("rate-limits", "2026-04-19T10:00:00Z"),
      event_type: "runtime.step.updated",
      payload: { label: "account rateLimits updated" },
    };
    const tokenUsage = {
      ...event("token-usage", "2026-04-19T10:00:01Z"),
      event_type: "runtime.step.updated",
      payload: { provider_event_type: "thread.tokenUsage.updated" },
    };
    const threadStatus = {
      ...event("thread-status", "2026-04-19T10:00:02Z"),
      event_type: "runtime.step.updated",
      payload: { label: "thread status changed" },
    };
    const visible = {
      ...event("visible", "2026-04-19T10:00:03Z"),
      event_type: "runtime.step.updated",
      payload: { label: "Reading workspace" },
    };

    expect(isNoisyRuntimeLabel("account rateLimits updated")).toBe(true);
    expect(isNoisyRuntimeLabel("thread tokenUsage updated")).toBe(true);
    expect(isNoisyRuntimeLabel("thread.status.changed")).toBe(true);
    expect(runtimeStepLabel(rateLimits)).toBeNull();
    expect(runtimeStepLabel(tokenUsage)).toBeNull();
    expect(runtimeStepLabel(threadStatus)).toBeNull();
    expect(latestRuntimeStepLabel([visible, rateLimits, tokenUsage, threadStatus])).toBe("Reading workspace");
    expect(latestRuntimeStepLabel([rateLimits, tokenUsage, threadStatus])).toBe("");
  });
});
