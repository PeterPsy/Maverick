import { describe, expect, it, vi } from "vitest";
import type { RuntimeEvent, RuntimeTurn, RuntimeWebSocketFrame } from "../api/client";
import {
  ApiError,
  isRuntimeSessionUnavailableError,
  runtimeEventFromWebSocketFrame,
  runtimeWebSocketUrl,
} from "../api/client";
import { firstPersistedRuntimeEventId, hydrateMissingTurnAnchors, inferActiveRuntimeTurn, lastRuntimeEventId, mergeRuntimeEvents } from "./runtimeEvents";
import { isNoisyRuntimeLabel, latestRuntimeStepLabel, runtimeStepLabel } from "./runtimeStepLabels";
import { eventsToMessages } from "./transcript";

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

function turn(status: string, overrides: Partial<RuntimeTurn> = {}): RuntimeTurn {
  return {
    turn_id: "turn-1",
    session_id: "session-1",
    workspace_id: "default",
    status,
    input_text: "user request",
    failure_reason: null,
    created_at: "2026-04-19T10:00:00Z",
    updated_at: "2026-04-19T10:00:02Z",
    ...overrides,
  };
}

describe("runtime websocket helpers", () => {
  it("builds a same-origin websocket URL with replay cursor", () => {
    vi.stubGlobal("window", { location: { protocol: "https:", host: "example.localhost" } });

    expect(runtimeWebSocketUrl("session 1", "event-1")).toBe(
      "wss://example.localhost/ws/runtime/sessions/session%201?last_event_id=event-1&initial_event_limit=500",
    );

    vi.unstubAllGlobals();
  });

  it("extracts runtime events and ignores transport frames", () => {
    const runtimeFrame: RuntimeWebSocketFrame = { type: "runtime.event", event: event("event-1", "2026-04-19T10:00:00Z") };
    const heartbeatFrame: RuntimeWebSocketFrame = { type: "runtime.heartbeat", session_id: "session-1", at: "2026-04-19T10:00:00Z" };
    const snapshotFrame: RuntimeWebSocketFrame = {
      type: "runtime.snapshot",
      session: { agent_id: "chat", effective_mode: "runtime", session_id: "session-1", status: "active", workspace_id: "default" },
      events: [event("event-1", "2026-04-19T10:00:00Z")],
      last_event_id: "event-1",
    };

    expect(runtimeEventFromWebSocketFrame(runtimeFrame)?.event_id).toBe("event-1");
    expect(runtimeEventFromWebSocketFrame(heartbeatFrame)).toBeNull();
    expect(runtimeEventFromWebSocketFrame(snapshotFrame)).toBeNull();
  });

  it("deduplicates and orders runtime events from WebSocket snapshot and live frames", () => {
    const merged = mergeRuntimeEvents(
      [event("event-2", "2026-04-19T10:00:01Z")],
      [event("event-1", "2026-04-19T10:00:00Z"), event("event-2", "2026-04-19T10:00:01Z")],
    );

    expect(merged.map((item) => item.event_id)).toEqual(["event-1", "event-2"]);
    expect(lastRuntimeEventId(merged)).toBe("event-2");
  });

  it("hydrates missing turn anchors from bounded WebSocket turn metadata", () => {
    const hydrated = hydrateMissingTurnAnchors(
      [
        { ...event("event-2", "2026-04-19T10:00:01Z"), event_type: "runtime.output.delta", payload: { text: "done" } },
        { ...event("event-3", "2026-04-19T10:00:02Z"), event_type: "runtime.output.final", payload: { text: "done" } },
      ],
      [
        {
          turn_id: "turn-1",
          session_id: "session-1",
          workspace_id: "default",
          status: "completed",
          input_text: "user request",
          client_message_id: "client-message-from-turn",
          failure_reason: null,
          created_at: "2026-04-19T10:00:00Z",
          updated_at: "2026-04-19T10:00:02Z",
        },
      ],
    );

    expect(hydrated[0]).toMatchObject({
      event_id: "synthetic-turn-anchor:turn-1",
      event_type: "runtime.turn.queued",
      payload: { input_text: "user request", client_message_id: "client-message-from-turn", synthetic_turn_anchor: true },
    });
    expect(firstPersistedRuntimeEventId(hydrated)).toBe("event-2");
    expect(eventsToMessages(hydrated)[0]).toMatchObject({ id: "client-message-from-turn", role: "human", content: "user request" });
    expect(eventsToMessages(hydrated).map((message) => [message.role, message.content])).toEqual([
      ["human", "user request"],
      ["agent", "done"],
    ]);
  });

  it("hydrates terminal turn status from bounded WebSocket turn metadata", () => {
    const hydrated = hydrateMissingTurnAnchors(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("started", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.started" },
        { ...event("delta", "2026-04-19T10:00:02Z"), event_type: "runtime.output.delta", payload: { text: "done" } },
      ],
      [turn("completed", { input_text: "work", updated_at: "2026-04-19T10:00:03Z" })],
    );

    expect(hydrated.at(-1)).toMatchObject({
      event_id: "synthetic-turn-status:turn-1",
      event_type: "runtime.turn.completed",
      payload: { status: "completed", synthetic_turn_status: true },
    });
    expect(firstPersistedRuntimeEventId(hydrated)).toBe("queued");
    expect(inferActiveRuntimeTurn(hydrated, "session-1")).toBeNull();
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

  it("treats timed-out runtime events as terminal for UI busy state", () => {
    const activeTurn = inferActiveRuntimeTurn(
      [
        { ...event("queued", "2026-04-19T10:00:00Z"), event_type: "runtime.turn.queued", payload: { input_text: "work" } },
        { ...event("started", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.started" },
        { ...event("timed-out", "2026-04-19T10:00:02Z"), event_type: "runtime.turn.timed-out", payload: { error: "watchdog timeout" } },
      ],
      "session-1",
    );

    expect(activeTurn).toBeNull();
  });

  it("treats a final output event as terminal for UI busy state", () => {
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
        { ...event("completed", "2026-04-19T10:00:01Z"), event_type: "runtime.turn.completed", payload: {} },
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

  it("classifies unavailable runtime sessions from API errors", () => {
    expect(
      isRuntimeSessionUnavailableError(
        new ApiError("runtime_session_not_found", { path: "/api/runtime/sessions/session-1/events", status: 404 }),
        "session-1",
      ),
    ).toBe(true);
    expect(
      isRuntimeSessionUnavailableError(
        new ApiError("forbidden", { path: "/api/runtime/sessions/session-2", status: 403 }),
        "session-1",
      ),
    ).toBe(false);
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
    expect(isNoisyRuntimeLabel("turn plan updated")).toBe(true);
    expect(runtimeStepLabel(rateLimits)).toBeNull();
    expect(runtimeStepLabel(tokenUsage)).toBeNull();
    expect(runtimeStepLabel(threadStatus)).toBeNull();
    expect(latestRuntimeStepLabel([visible, rateLimits, tokenUsage, threadStatus])).toBe("Reading workspace");
    expect(latestRuntimeStepLabel([rateLimits, tokenUsage, threadStatus])).toBe("");
  });

  it("filters provider hook lifecycle labels from live runtime labels", () => {
    const visible = {
      ...event("visible", "2026-04-19T10:00:00Z"),
      event_type: "runtime.step.updated",
      payload: { label: "Reading workspace" },
    };
    const hookStarted = {
      ...event("hook-started", "2026-04-19T10:00:01Z"),
      event_type: "runtime.step.updated",
      payload: { label: "hook started" },
    };
    const hookCompleted = {
      ...event("hook-completed", "2026-04-19T10:00:02Z"),
      event_type: "runtime.step.updated",
      payload: { label: "hook.completed" },
    };

    expect(isNoisyRuntimeLabel("hook started")).toBe(true);
    expect(isNoisyRuntimeLabel("hook.completed")).toBe(true);
    expect(runtimeStepLabel(hookStarted)).toBeNull();
    expect(runtimeStepLabel(hookCompleted)).toBeNull();
    expect(latestRuntimeStepLabel([visible, hookStarted, hookCompleted])).toBe("Reading workspace");
    expect(latestRuntimeStepLabel([hookStarted, hookCompleted])).toBe("");
  });

  it("filters command execution telemetry from live runtime labels", () => {
    const outputDelta = {
      ...event("output-delta", "2026-04-19T10:00:00Z"),
      event_type: "runtime.step.updated",
      payload: { label: "item commandExecution outputDelta", provider_event_type: "item/commandExecution/outputDelta" },
    };
    const terminalInteraction = {
      ...event("terminal-interaction", "2026-04-19T10:00:01Z"),
      event_type: "runtime.step.updated",
      payload: { provider_event_type: "item.commandExecution.terminalInteraction" },
    };
    const visible = {
      ...event("visible", "2026-04-19T10:00:02Z"),
      event_type: "runtime.step.updated",
      payload: { label: "Reading workspace" },
    };

    expect(isNoisyRuntimeLabel("item commandExecution outputDelta")).toBe(true);
    expect(isNoisyRuntimeLabel("item.commandExecution.terminalInteraction")).toBe(true);
    expect(runtimeStepLabel(outputDelta)).toBeNull();
    expect(runtimeStepLabel(terminalInteraction)).toBeNull();
    expect(latestRuntimeStepLabel([visible, outputDelta, terminalInteraction])).toBe("Reading workspace");
  });
});
