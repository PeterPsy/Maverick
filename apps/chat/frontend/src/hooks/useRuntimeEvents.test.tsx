/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";
import type { PendingMessage } from "../lib/messageState";
import { useRuntimeEvents } from "./useRuntimeEvents";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;

  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = MockWebSocket.OPEN;
  sent: string[] = [];
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3;
  }

  send(payload: string) {
    this.sent.push(payload);
  }
}

const session: RuntimeSession = {
  agent_id: "chat",
  effective_mode: "runtime",
  session_id: "session-1",
  status: "active",
  workspace_id: "default",
};

function event(eventId: string): RuntimeEvent {
  return {
    event_id: eventId,
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.output.delta",
    payload: {},
    created_at: "2026-04-19T10:00:00Z",
  };
}

function RuntimeEventsHarness({ initialEvents, olderHistoryRequestId = 0 }: { initialEvents: RuntimeEvent[]; olderHistoryRequestId?: number }) {
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>(initialEvents);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [, setIsOlderHistoryLoading] = useState(false);
  const [, setError] = useState<string | null>(null);
  const [, setPendingUserMessages] = useState<PendingMessage[]>([]);
  void activeSession;
  void events;

  useRuntimeEvents({
    activeTurn,
    hasMoreHistory,
    olderHistoryRequestId,
    runtimeSessionId: "session-1",
    setActiveSession,
    setActiveTurn,
    setError,
    setEvents,
    setHasMoreHistory,
    setIsOlderHistoryLoading,
    setPendingUserMessages,
  });

  return null;
}

describe("useRuntimeEvents", () => {
  let originalWebSocket: typeof WebSocket | undefined;
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    root?.unmount();
    container?.remove();
    root = null;
    container = null;
    globalThis.WebSocket = originalWebSocket as typeof WebSocket;
    vi.useRealTimers();
  });

  it("refreshes the bounded tail before using cached event cursors for reconnects", async () => {
    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[event("cached-event")]} />);
    });

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toBe("ws://localhost:3000/ws/runtime/sessions/session-1?initial_event_limit=500");

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.snapshot",
          session,
          events: [event("tail-event")],
          last_event_id: "tail-event",
          has_more_before: false,
          oldest_event_id: "tail-event",
        }),
      } as MessageEvent);
    });

    await act(async () => {
      MockWebSocket.instances[0].onclose?.({ code: 1006 } as CloseEvent);
      vi.advanceTimersByTime(500);
    });

    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).toBe(
      "ws://localhost:3000/ws/runtime/sessions/session-1?last_event_id=tail-event&initial_event_limit=500",
    );
  });

  it("uses the oldest persisted event cursor after hydrating missing turn anchors", async () => {
    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[]} />);
    });

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.snapshot",
          session,
          events: [event("event-2"), { ...event("event-3"), event_type: "runtime.output.final", payload: { text: "done" } }],
          turns: [
            {
              turn_id: "turn-1",
              session_id: "session-1",
              workspace_id: "default",
              status: "completed",
              input_text: "user request",
              failure_reason: null,
              created_at: "2026-04-19T09:59:59Z",
              updated_at: "2026-04-19T10:00:01Z",
            },
          ],
          last_event_id: "event-3",
          has_more_before: true,
          oldest_event_id: "event-2",
        }),
      } as MessageEvent);
    });

    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[]} olderHistoryRequestId={1} />);
    });

    expect(JSON.parse(MockWebSocket.instances[0].sent[0])).toEqual({
      type: "runtime.history.before",
      before_event_id: "event-2",
      limit: 250,
    });
  });
});
