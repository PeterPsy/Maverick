/**
 * @vitest-environment happy-dom
 */
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatUsageSummary, RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";
import type { PendingMessage } from "../lib/messageState";
import { eventsToMessages } from "../lib/transcript";
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

type RuntimeEventsHarnessState = {
  activeSession: RuntimeSession | null;
  activeTurn: RuntimeTurn | null;
  error: string | null;
  events: RuntimeEvent[];
  pendingUserMessages: PendingMessage[];
  usage: ChatUsageSummary | null;
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

function RuntimeEventsHarness({
  initialEvents,
  initialPendingUserMessages = [],
  olderHistoryRequestId = 0,
  onState,
  runtimeSessionId = "session-1",
}: {
  initialEvents: RuntimeEvent[];
  initialPendingUserMessages?: PendingMessage[];
  olderHistoryRequestId?: number;
  onState?: (state: RuntimeEventsHarnessState) => void;
  runtimeSessionId?: string;
}) {
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>(initialEvents);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [, setIsOlderHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingMessage[]>(initialPendingUserMessages);
  const [usage, setUsage] = useState<ChatUsageSummary | null>(null);

  useEffect(() => {
    onState?.({ activeSession, activeTurn, error, events, pendingUserMessages, usage });
  }, [activeSession, activeTurn, error, events, onState, pendingUserMessages, usage]);

  useRuntimeEvents({
    activeTurn,
    hasMoreHistory,
    olderHistoryRequestId,
    onUsageSnapshot: setUsage,
    runtimeSessionId,
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

  it("applies authoritative usage from snapshots and live usage events", async () => {
    let latestState: RuntimeEventsHarnessState | null = null;
    const usage = {
      workspace_id: "default",
      root_session_id: "session-1",
      tokens: { input_tokens: 80, cached_input_tokens: 10, cache_write_input_tokens: 0, output_tokens: 10, reasoning_output_tokens: 0, total_tokens: 100 },
      direct_tokens: { input_tokens: 80, cached_input_tokens: 10, cache_write_input_tokens: 0, output_tokens: 10, reasoning_output_tokens: 0, total_tokens: 100 },
      delegated_tokens: { input_tokens: 0, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_output_tokens: 0, total_tokens: 0 },
      context_tokens: 50,
      context_window_tokens: 200,
      context_used_percent: 25,
      token_accuracy: "exact",
      context_accuracy: "exact",
      provider_ids: ["codex"],
      model_ids: ["gpt-test"],
      estimated_cost_microusd: null,
      sample_count: 1,
      coverage_since: "2026-04-19T10:00:00Z",
      updated_at: "2026-04-19T10:00:00Z",
    } satisfies ChatUsageSummary;
    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[]} onState={(state) => { latestState = state; }} />);
    });

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.snapshot",
          session,
          events: [],
          last_event_id: null,
          usage,
        }),
      } as MessageEvent);
    });
    expect((latestState as RuntimeEventsHarnessState | null)?.usage?.tokens.total_tokens).toBe(100);

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.event",
          event: {
            ...event("usage-event"),
            event_type: "runtime.usage.updated",
            payload: { ...usage, tokens: { ...usage.tokens, total_tokens: 125 } },
          },
        }),
      } as MessageEvent);
    });
    expect((latestState as RuntimeEventsHarnessState | null)?.usage?.tokens.total_tokens).toBe(125);
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

  it("ignores frames and errors from sockets that are no longer current", async () => {
    let latestState: RuntimeEventsHarnessState | null = null;
    const onState = (state: RuntimeEventsHarnessState) => {
      latestState = state;
    };

    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[]} onState={onState} />);
    });
    const staleSocket = MockWebSocket.instances[0];

    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[]} onState={onState} runtimeSessionId="session-2" />);
    });

    await act(async () => {
      staleSocket.onmessage?.({
        data: JSON.stringify({ type: "runtime.event", event: event("stale-event") }),
      } as MessageEvent);
      staleSocket.onerror?.();
    });

    const state = latestState as RuntimeEventsHarnessState | null;
    expect((state?.events ?? []).map((item) => item.event_id)).toEqual([]);
    expect(state?.error ?? null).toBeNull();
  });

  it("carries plain hosted runtime events through WebSocket state into the transcript", async () => {
    let latestState: RuntimeEventsHarnessState | null = null;
    const onState = (state: RuntimeEventsHarnessState) => {
      latestState = state;
    };

    await act(async () => {
      root?.render(<RuntimeEventsHarness initialEvents={[]} onState={onState} />);
    });

    const plainSession: RuntimeSession = {
      ...session,
      runtime_mode: "plain_hosted_chat",
      provider_id: "hosted-text-runtime",
    };
    const queued = {
      ...event("plain-queued"),
      event_type: "runtime.turn.queued",
      payload: { input_text: "Hello hosted", client_message_id: "client-plain", provider_id: "hosted-text-runtime" },
      created_at: "2026-04-19T10:00:00.000Z",
    };

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.snapshot",
          session: plainSession,
          events: [queued],
          last_event_id: "plain-queued",
          has_more_before: false,
          oldest_event_id: "plain-queued",
        }),
      } as MessageEvent);
    });

    for (const runtimeEvent of [
      {
        ...event("plain-delta-1"),
        event_type: "runtime.output.delta",
        payload: { text: "Hosted ", provider_id: "groq", runtime_mode: "plain_hosted_chat" },
        created_at: "2026-04-19T10:00:01.000Z",
      },
      {
        ...event("plain-delta-2"),
        event_type: "runtime.output.delta",
        payload: { text: "answer", provider_id: "groq", runtime_mode: "plain_hosted_chat" },
        created_at: "2026-04-19T10:00:02.000Z",
      },
      {
        ...event("plain-final"),
        event_type: "runtime.output.final",
        payload: { text: "", complete_text: "Hosted answer", provider_id: "groq", exit_code: 0 },
        created_at: "2026-04-19T10:00:03.000Z",
      },
      {
        ...event("plain-completed"),
        event_type: "runtime.turn.completed",
        payload: { provider_id: "groq" },
        created_at: "2026-04-19T10:00:04.000Z",
      },
    ] satisfies RuntimeEvent[]) {
      await act(async () => {
        MockWebSocket.instances[0].onmessage?.({
          data: JSON.stringify({ type: "runtime.event", event: runtimeEvent }),
        } as MessageEvent);
      });
    }

    const state = latestState as RuntimeEventsHarnessState | null;
    expect(state?.activeSession?.runtime_mode).toBe("plain_hosted_chat");
    expect(state?.activeTurn).toBeNull();
    expect((state?.events ?? []).map((item) => item.event_type)).toContain("runtime.turn.completed");
    expect(eventsToMessages(state?.events ?? [])).toMatchObject([
      { id: "client-plain", role: "human", content: "Hello hosted", status: "complete" },
      { role: "agent", content: "Hosted answer", status: "complete" },
    ]);
  });

  it("removes pending messages from a terminal snapshot without an active turn", async () => {
    let latestState: RuntimeEventsHarnessState | null = null;
    const onState = (state: RuntimeEventsHarnessState) => {
      latestState = state;
    };

    await act(async () => {
      root?.render(
        <RuntimeEventsHarness
          initialEvents={[]}
          initialPendingUserMessages={[
            {
              clientMessageId: "client-completed",
              content: "Done while away",
              createdAt: "2026-04-19T09:59:59Z",
              appReferences: [],
              attachments: [],
            },
          ]}
          onState={onState}
        />,
      );
    });

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.snapshot",
          session,
          events: [
            {
              ...event("queued-completed"),
              event_type: "runtime.turn.queued",
              payload: { input_text: "Done while away", client_message_id: "client-completed" },
              created_at: "2026-04-19T10:00:00.000Z",
            },
            {
              ...event("final-completed"),
              event_type: "runtime.output.final",
              payload: { complete_text: "Done" },
              created_at: "2026-04-19T10:00:01.000Z",
            },
          ],
          last_event_id: "final-completed",
          has_more_before: false,
          oldest_event_id: "queued-completed",
        }),
      } as MessageEvent);
    });

    const state = latestState as RuntimeEventsHarnessState | null;
    expect(state?.activeTurn).toBeNull();
    expect(state?.pendingUserMessages).toEqual([]);
  });

  it("does not complete the root turn or clear its pending message for participant final output", async () => {
    let latestState: RuntimeEventsHarnessState | null = null;
    const onState = (state: RuntimeEventsHarnessState) => {
      latestState = state;
    };

    await act(async () => {
      root?.render(
        <RuntimeEventsHarness
          initialEvents={[]}
          initialPendingUserMessages={[
            {
              clientMessageId: "client-root",
              content: "Coordinate the run",
              createdAt: "2026-04-19T09:59:59Z",
              appReferences: [],
              attachments: [],
            },
          ]}
          onState={onState}
        />,
      );
    });

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.snapshot",
          session,
          events: [
            {
              ...event("queued-root"),
              event_type: "runtime.turn.queued",
              payload: { input_text: "Coordinate the run", client_message_id: "client-root" },
              created_at: "2026-04-19T10:00:00.000Z",
            },
            {
              ...event("started-root"),
              event_type: "runtime.turn.started",
              created_at: "2026-04-19T10:00:01.000Z",
            },
            {
              ...event("participant-final"),
              event_type: "runtime.output.final",
              payload: {
                text: "Participant finished its block.",
                inter_agent_projection: "participant_runtime_event",
                inter_agent_run_id: "run-1",
                inter_agent_participant_id: "researcher",
              },
              created_at: "2026-04-19T10:00:02.000Z",
            },
          ],
          last_event_id: "participant-final",
          has_more_before: false,
          oldest_event_id: "queued-root",
        }),
      } as MessageEvent);
    });

    const state = latestState as RuntimeEventsHarnessState | null;
    expect(state?.activeTurn).toMatchObject({ turn_id: "turn-1", status: "active" });
    expect(state?.pendingUserMessages).toMatchObject([{ clientMessageId: "client-root" }]);
  });
});
