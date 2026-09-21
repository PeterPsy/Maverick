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
import type { HistoryRestoreRequest } from './useRuntimeHistoryWindow';

vi.mock('../pwaCache', async (importOriginal) => ({
  ...await importOriginal<typeof import('../pwaCache')>(),
  readChatDisplay: vi.fn().mockRejectedValue(new Error('No persisted display in this test')),
  invalidateChatDisplay: vi.fn(),
}));

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;
  static failNext = false;

  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = MockWebSocket.OPEN;
  sent: string[] = [];
  url: string;

  constructor(url: string) {
    if (MockWebSocket.failNext) {
      MockWebSocket.failNext = false;
      throw new Error('connection unavailable');
    }
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
  hasNewerHistory: boolean;
  restoredHistoryRequestId: number;
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
  newerHistoryRequestId = 0,
  latestHistoryRequestId = 0,
  followLatestRef,
  historyRestoreRequest,
  onState,
  runtimeSessionId = "session-1",
}: {
  initialEvents: RuntimeEvent[];
  initialPendingUserMessages?: PendingMessage[];
  olderHistoryRequestId?: number;
  newerHistoryRequestId?: number;
  latestHistoryRequestId?: number;
  followLatestRef?: { current: boolean };
  historyRestoreRequest?: HistoryRestoreRequest;
  onState?: (state: RuntimeEventsHarnessState) => void;
  runtimeSessionId?: string;
}) {
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>(initialEvents);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [hasNewerHistory, setHasNewerHistory] = useState(false);
  const [restoredHistoryRequestId, setRestoredHistoryRequestId] = useState(0);
  const [, setIsOlderHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingMessage[]>(initialPendingUserMessages);
  const [usage, setUsage] = useState<ChatUsageSummary | null>(null);

  useEffect(() => {
    onState?.({ activeSession, activeTurn, error, events, pendingUserMessages, usage, hasNewerHistory, restoredHistoryRequestId });
  }, [activeSession, activeTurn, error, events, onState, pendingUserMessages, usage, hasNewerHistory, restoredHistoryRequestId]);

  useRuntimeEvents({
    activeTurn,
    hasMoreHistory,
    olderHistoryRequestId,
    newerHistoryRequestId,
    latestHistoryRequestId,
    followLatestRef,
    hasNewerHistory,
    setHasNewerHistory,
    historyRestoreRequest,
    setRestoredHistoryRequestId,
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
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    MockWebSocket.instances = [];
    MockWebSocket.failNext = false;
    originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  it('restores one contiguous reading window after connection and acknowledges its committed data', async () => {
    const onState = vi.fn();
    await act(async () => root?.render(<RuntimeEventsHarness initialEvents={[]} onState={onState}
      historyRestoreRequest={{ id: 1, sessionId: 'session-1', eventId: 'old-anchor' }} />));
    const socket = MockWebSocket.instances[0];
    await act(async () => socket.onmessage?.({ data: JSON.stringify({ type: 'runtime.snapshot', session, events: [event('latest')] }) } as MessageEvent));
    expect(socket.sent).toHaveLength(1);
    const request = JSON.parse(socket.sent[0]);
    expect(request).toMatchObject({ type: 'runtime.history.around', around_event_id: 'old-anchor' });
    await act(async () => socket.onmessage?.({ data: JSON.stringify({ type: 'runtime.history.page', direction: 'around',
      request_id: request.request_id, events: [event('old-anchor')], has_more_before: true, has_more_after: true }) } as MessageEvent));
    const final = onState.mock.calls.at(-1)![0] as RuntimeEventsHarnessState;
    expect(final.events.map(event => event.event_id)).toEqual(['old-anchor']);
    expect(final.hasNewerHistory).toBe(true);
    expect(final.restoredHistoryRequestId).toBe(1);
    const acknowledged = onState.mock.calls.map(([state]) => state as RuntimeEventsHarnessState)
      .filter(state => state.restoredHistoryRequestId === 1);
    expect(acknowledged.every(state => state.events[0]?.event_id === 'old-anchor')).toBe(true);
  });

  it('bounds cold data while reading history, tracks live control, and rejects superseded pages', async () => {
    const onState = vi.fn();
    const followLatestRef = { current: false };
    const props = { initialEvents: [], onState, followLatestRef };
    const historic = (index: number): RuntimeEvent => ({ ...event(`history-${index}`), turn_id: null,
      created_at: new Date(Date.UTC(2026, 0, 1) + index * 1000).toISOString() });
    const emit = (frame: unknown) => MockWebSocket.instances.at(-1)!.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);
    const state = () => onState.mock.calls.at(-1)![0] as RuntimeEventsHarnessState;
    await act(async () => { root?.render(<RuntimeEventsHarness {...props} />); });
    await act(async () => emit({ type: 'runtime.snapshot', session,
      events: Array.from({ length: 5900 }, (_, index) => historic(index)), has_more_before: true }));
    await act(async () => {
      for (let index = 5900; index < 6200; index++) emit({ type: 'runtime.event', event: historic(index) });
      vi.advanceTimersByTime(60);
    });
    expect(state().events.length).toBeLessThanOrEqual(6000);
    expect(state().hasNewerHistory).toBe(true);
    const retained = state().events;
    const live = { ...event('live-start'), turn_id: 'live-turn', event_type: 'runtime.turn.started' };
    await act(async () => { emit({ type: 'runtime.event', event: live }); vi.advanceTimersByTime(20); });
    expect(state().events).toBe(retained);
    expect(state().activeTurn?.turn_id).toBe('live-turn');
    await act(async () => { root?.render(<RuntimeEventsHarness {...props} olderHistoryRequestId={1} />); });
    const before = JSON.parse(MockWebSocket.instances.at(-1)!.sent.at(-1)!);
    await act(async () => emit({ type: 'runtime.history.page', direction: 'before', request_id: before.request_id,
      events: [historic(-1)], has_more_before: false }));
    expect(state().events[0].event_id).toBe('history--1');
    expect(state().activeTurn?.turn_id).toBe('live-turn');
    await act(async () => { root?.render(<RuntimeEventsHarness {...props} olderHistoryRequestId={1} newerHistoryRequestId={1} />); });
    const after = JSON.parse(MockWebSocket.instances.at(-1)!.sent.at(-1)!);
    expect(after.type).toBe('runtime.history.after');
    expect(after.after_event_id).toBe(retained.at(-1)!.event_id);
    await act(async () => { root?.render(<RuntimeEventsHarness {...props} olderHistoryRequestId={1} newerHistoryRequestId={1} latestHistoryRequestId={1} />); });
    const latest = JSON.parse(MockWebSocket.instances.at(-1)!.sent.at(-1)!);
    const beforeStale = state().events;
    await act(async () => emit({ type: 'runtime.history.page', direction: 'after', request_id: after.request_id,
      events: [historic(4800)], has_more_after: true }));
    expect(state().events).toBe(beforeStale);
    await act(async () => emit({ type: 'runtime.history.page', direction: 'latest', request_id: latest.request_id,
      events: [historic(6200)], has_more_before: true, has_more_after: false }));
    expect(state().events.map(item => item.event_id)).toEqual(['history-6200']);
    expect(state().hasNewerHistory).toBe(false);
    await act(async () => emit({ type: 'runtime.event', event: { ...live, event_id: 'live-end', event_type: 'runtime.turn.completed' } }));
    expect(state().activeTurn).toBeNull();
  });

  it('closes hidden/offline streams and reconnects once with an authoritative snapshot', async () => {
    await act(async () => { root?.render(<RuntimeEventsHarness initialEvents={[]} />); });
    const first = MockWebSocket.instances[0];
    await act(async () => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(first.readyState).toBe(3);
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(MockWebSocket.instances).toHaveLength(1);
    await act(async () => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).not.toContain('last_event_id');
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(MockWebSocket.instances).toHaveLength(2);
    delete (document as unknown as Record<string, unknown>).hidden;
  });

  afterEach(() => {
    root?.unmount();
    container?.remove();
    root = null;
    container = null;
    globalThis.WebSocket = originalWebSocket as typeof WebSocket;
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('backs off flapping connections, caps retries, and resets only after a snapshot', async () => {
    await act(async () => { root?.render(<RuntimeEventsHarness initialEvents={[]} />); });
    for (const delay of [500, 1000, 2000, 4000, 8000, 16000, 30000, 30000]) {
      const current = MockWebSocket.instances.at(-1)!;
      const count = MockWebSocket.instances.length;
      await act(async () => {
        current.onopen?.();
        current.onclose?.({ code: 1006 } as CloseEvent);
        vi.advanceTimersByTime(delay - 1);
      });
      expect(MockWebSocket.instances).toHaveLength(count);
      await act(async () => { vi.advanceTimersByTime(1); });
      expect(MockWebSocket.instances).toHaveLength(count + 1);
    }
    const count = MockWebSocket.instances.length;
    await act(async () => {
      const current = MockWebSocket.instances.at(-1)!;
      current.onmessage?.({ data: JSON.stringify({ type: 'runtime.snapshot', session, events: [] }) } as MessageEvent);
      current.onclose?.({ code: 1006 } as CloseEvent);
      vi.advanceTimersByTime(500);
    });
    expect(MockWebSocket.instances).toHaveLength(count + 1);
  });

  it('ignores callbacks from replaced sockets without corrupting state or reconnecting again', async () => {
    const onState = vi.fn();
    await act(async () => { root?.render(<RuntimeEventsHarness initialEvents={[]} onState={onState} />); });
    const first = MockWebSocket.instances[0];
    await act(async () => {
      first.onclose?.({ code: 1006 } as CloseEvent);
      vi.advanceTimersByTime(500);
    });
    const current = MockWebSocket.instances[1];
    await act(async () => {
      current.onmessage?.({ data: JSON.stringify({ type: 'runtime.snapshot', session, events: [event('current')] }) } as MessageEvent);
      first.onmessage?.({ data: JSON.stringify({ type: 'runtime.snapshot', session, events: [event('stale')] }) } as MessageEvent);
      first.onerror?.();
      first.onopen?.();
      first.onclose?.({ code: 1006 } as CloseEvent);
      vi.advanceTimersByTime(1000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(onState.mock.lastCall?.[0].events.map((item: RuntimeEvent) => item.event_id)).toEqual(['current']);
    expect(onState.mock.lastCall?.[0].error).toBeNull();
  });

  it('recovers a constructor failure with a jittered retry', async () => {
    MockWebSocket.failNext = true;
    vi.mocked(Math.random).mockReturnValue(0);
    const onState = vi.fn();
    await act(async () => { root?.render(<RuntimeEventsHarness initialEvents={[]} onState={onState} />); });
    expect(onState.mock.lastCall?.[0].error).toBe('Runtime WebSocket is unavailable.');
    await act(async () => { vi.advanceTimersByTime(399); });
    expect(MockWebSocket.instances).toHaveLength(0);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(MockWebSocket.instances).toHaveLength(1);
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
      request_id: "session-1:1",
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
