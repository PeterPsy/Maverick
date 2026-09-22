/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../api/client";
import { RuntimeThreadSource } from "./runtimeThreadSource";

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.onclose?.({ code: 1000 } as CloseEvent);
  }
}

class MockBroadcastChannel {
  static channels = new Map<string, Set<MockBroadcastChannel>>();

  name: string;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(name: string) {
    this.name = name;
    const peers = MockBroadcastChannel.channels.get(name) || new Set<MockBroadcastChannel>();
    peers.add(this);
    MockBroadcastChannel.channels.set(name, peers);
  }

  postMessage(data: unknown) {
    const peers = MockBroadcastChannel.channels.get(this.name) || new Set<MockBroadcastChannel>();
    for (const peer of peers) {
      if (peer === this) {
        continue;
      }
      queueMicrotask(() => peer.onmessage?.({ data } as MessageEvent));
    }
  }

  close() {
    MockBroadcastChannel.channels.get(this.name)?.delete(this);
  }
}

async function flushChannelMessages() {
  for (let index = 0; index < 4; index += 1) {
    await Promise.resolve();
  }
}

function okJson(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

describe("RuntimeThreadSource", () => {
  let originalBroadcastChannel: typeof BroadcastChannel | undefined;
  let originalWebSocket: typeof WebSocket | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    window.sessionStorage.clear();
    MockBroadcastChannel.channels.clear();
    MockWebSocket.instances = [];
    originalBroadcastChannel = globalThis.BroadcastChannel;
    originalWebSocket = globalThis.WebSocket;
    globalThis.BroadcastChannel = MockBroadcastChannel as unknown as typeof BroadcastChannel;
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    globalThis.BroadcastChannel = originalBroadcastChannel as typeof BroadcastChannel;
    globalThis.WebSocket = originalWebSocket as typeof WebSocket;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('backs off failed streams and ignores callbacks from a replaced socket', () => {
    const source = new RuntimeThreadSource({ leaderElectionDelayMs: 5, restFallbackDelayMs: 60_000 });
    const onError = vi.fn();
    const onFrame = vi.fn();
    const unsubscribe = source.subscribe({ onError, onFrame });
    vi.advanceTimersByTime(5);
    const first = MockWebSocket.instances[0];
    first.onclose?.({ code: 1006 } as CloseEvent);
    vi.advanceTimersByTime(500);
    const second = MockWebSocket.instances[1];
    second.onopen?.();
    first.onerror?.();
    first.onmessage?.({ data: JSON.stringify({ type: 'runtime.thread.snapshot', threads: [] }) } as MessageEvent);
    first.onclose?.({ code: 1006 } as CloseEvent);
    expect(onError.mock.lastCall).toEqual([null]);
    expect(onFrame).not.toHaveBeenCalled();
    second.onclose?.({ code: 1006 } as CloseEvent);
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(3);
    const third = MockWebSocket.instances[2];
    third.onmessage?.({ data: JSON.stringify({ type: 'runtime.thread.snapshot', workspace_id: 'default', threads: [] }) } as MessageEvent);
    third.onclose?.({ code: 1006 } as CloseEvent);
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances).toHaveLength(4);
    unsubscribe();
    vi.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances).toHaveLength(4);
  });

  it("elects one WebSocket source for separate same-tab subscribers", async () => {
    const firstFrames: unknown[] = [];
    const secondFrames: unknown[] = [];
    const firstSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5 });
    const secondSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5 });

    const unsubscribeFirst = firstSource.subscribe({ onError: () => undefined, onFrame: (frame) => firstFrames.push(frame) });
    const unsubscribeSecond = secondSource.subscribe({ onError: () => undefined, onFrame: (frame) => secondFrames.push(frame) });
    await flushChannelMessages();

    vi.advanceTimersByTime(5);
    await flushChannelMessages();

    expect(MockWebSocket.instances).toHaveLength(1);

    const snapshot = { type: "runtime.thread.snapshot", workspace_id: "default", threads: [], at: "2026-07-08T12:00:00.000Z" };
    MockWebSocket.instances[0].onmessage?.({ data: JSON.stringify(snapshot) } as MessageEvent);
    await flushChannelMessages();

    expect(firstFrames).toEqual([snapshot]);
    expect(secondFrames).toEqual([snapshot]);

    unsubscribeFirst();
    unsubscribeSecond();
  });

  it("replays the current catalog to a late subscriber on the same source", async () => {
    const firstFrames: unknown[] = [];
    const secondFrames: unknown[] = [];
    const source = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5 });
    const firstThread = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "First" });
    const secondThread = thread({
      thread_id: "thread-2",
      runtime_session_id: "session-2",
      title: "Second",
      created_at: "2026-07-08T12:00:01.000Z",
      updated_at: "2026-07-08T12:00:01.000Z",
    });

    const unsubscribeFirst = source.subscribe({ onError: () => undefined, onFrame: (frame) => firstFrames.push(frame) });
    vi.advanceTimersByTime(5);
    await flushChannelMessages();

    expect(MockWebSocket.instances).toHaveLength(1);

    MockWebSocket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: [firstThread],
        at: "2026-07-08T12:00:00.000Z",
      }),
    } as MessageEvent);
    MockWebSocket.instances[0].onmessage?.({
      data: JSON.stringify({ type: "runtime.thread.changed", workspace_id: "default", action: "created", thread: secondThread }),
    } as MessageEvent);

    const unsubscribeSecond = source.subscribe({ onError: () => undefined, onFrame: (frame) => secondFrames.push(frame) });

    expect(firstFrames).toHaveLength(2);
    expect(secondFrames).toEqual([
      expect.objectContaining({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: [secondThread, firstThread],
      }),
    ]);

    unsubscribeFirst();
    unsubscribeSecond();
  });

  it("replays the current catalog to a late BroadcastChannel peer", async () => {
    const firstFrames: unknown[] = [];
    const secondFrames: unknown[] = [];
    const firstSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5 });
    const secondSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5 });
    const firstThread = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "First" });

    const unsubscribeFirst = firstSource.subscribe({ onError: () => undefined, onFrame: (frame) => firstFrames.push(frame) });
    await flushChannelMessages();
    vi.advanceTimersByTime(5);
    await flushChannelMessages();

    expect(MockWebSocket.instances).toHaveLength(1);

    const snapshot = {
      type: "runtime.thread.snapshot",
      workspace_id: "default",
      threads: [firstThread],
      at: "2026-07-08T12:00:00.000Z",
    };
    MockWebSocket.instances[0].onmessage?.({ data: JSON.stringify(snapshot) } as MessageEvent);
    await flushChannelMessages();

    const unsubscribeSecond = secondSource.subscribe({ onError: () => undefined, onFrame: (frame) => secondFrames.push(frame) });
    await flushChannelMessages();

    expect(firstFrames).toEqual([snapshot]);
    expect(secondFrames).toEqual([snapshot]);
    expect(MockWebSocket.instances).toHaveLength(1);

    unsubscribeFirst();
    unsubscribeSecond();
  });

  it("replays the complete current catalog when a known peer resubscribes", async () => {
    const firstFrames: unknown[] = [];
    const secondFrames: unknown[] = [];
    const resumedFrames: unknown[] = [];
    const firstSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5, restFallbackDelayMs: 60_000 });
    const secondSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5, restFallbackDelayMs: 60_000 });
    const firstThread = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "First" });
    const secondThread = thread({
      thread_id: "thread-2",
      runtime_session_id: "session-2",
      title: "Second",
      created_at: "2026-07-08T12:00:01.000Z",
      updated_at: "2026-07-08T12:00:01.000Z",
    });

    const unsubscribeFirst = firstSource.subscribe({ onError: () => undefined, onFrame: (frame) => firstFrames.push(frame) });
    const unsubscribeSecond = secondSource.subscribe({ onError: () => undefined, onFrame: (frame) => secondFrames.push(frame) });
    await flushChannelMessages();
    vi.advanceTimersByTime(5);
    await flushChannelMessages();

    expect(MockWebSocket.instances).toHaveLength(1);
    MockWebSocket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: [firstThread],
        at: "2026-07-08T12:00:00.000Z",
      }),
    } as MessageEvent);
    expect([firstFrames.length, secondFrames.length].sort()).toEqual([0, 1]);
    const firstIsLeader = firstFrames.length === 1;
    await flushChannelMessages();

    const followerSource = firstIsLeader ? secondSource : firstSource;
    const unsubscribeLeader = firstIsLeader ? unsubscribeFirst : unsubscribeSecond;
    const unsubscribeFollower = firstIsLeader ? unsubscribeSecond : unsubscribeFirst;
    unsubscribeFollower();

    MockWebSocket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: "runtime.thread.changed",
        workspace_id: "default",
        action: "created",
        thread: secondThread,
      }),
    } as MessageEvent);
    await flushChannelMessages();

    const unsubscribeResumed = followerSource.subscribe({
      onError: () => undefined,
      onFrame: (frame) => resumedFrames.push(frame),
    });
    await flushChannelMessages();

    expect(resumedFrames).toEqual([
      expect.objectContaining({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: [secondThread, firstThread],
      }),
    ]);
    expect(MockWebSocket.instances).toHaveLength(1);

    unsubscribeResumed();
    unsubscribeLeader();
  });

  it("cancels the REST fallback when the WebSocket snapshot arrives first", async () => {
    const frames: unknown[] = [];
    const source = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5, restFallbackDelayMs: 20 });
    const snapshot = { type: "runtime.thread.snapshot", workspace_id: "default", threads: [], at: "2026-07-08T12:00:00.000Z" };
    vi.stubGlobal("fetch", vi.fn());

    const unsubscribe = source.subscribe({ onError: () => undefined, onFrame: (frame) => frames.push(frame) });
    await flushChannelMessages();
    vi.advanceTimersByTime(5);
    await flushChannelMessages();

    expect(MockWebSocket.instances).toHaveLength(1);

    MockWebSocket.instances[0].onmessage?.({ data: JSON.stringify(snapshot) } as MessageEvent);
    vi.advanceTimersByTime(20);
    await flushChannelMessages();

    expect(fetch).not.toHaveBeenCalled();
    expect(frames).toEqual([snapshot]);

    unsubscribe();
  });

  it("shares one REST fallback from the elected source across same-tab peers", async () => {
    const firstFrames: unknown[] = [];
    const secondFrames: unknown[] = [];
    const firstThread = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "First" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        okJson({
          workspace_id: "default",
          threads: [firstThread],
          threads_page: { limit: 50, has_more: false, cursor: null, sort: "recency_desc" },
        }),
      ),
    );

    const firstSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5, restFallbackDelayMs: 20 });
    const secondSource = new RuntimeThreadSource({ followerTimeoutMs: 1000, leaderElectionDelayMs: 5, restFallbackDelayMs: 20 });

    const unsubscribeFirst = firstSource.subscribe({ onError: () => undefined, onFrame: (frame) => firstFrames.push(frame) });
    const unsubscribeSecond = secondSource.subscribe({ onError: () => undefined, onFrame: (frame) => secondFrames.push(frame) });
    await flushChannelMessages();

    vi.advanceTimersByTime(5);
    await flushChannelMessages();
    vi.advanceTimersByTime(20);
    await flushChannelMessages();

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(firstFrames).toEqual([
      expect.objectContaining({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: [firstThread],
      }),
    ]);
    expect(secondFrames).toEqual([
      expect.objectContaining({
        type: "runtime.thread.snapshot",
        workspace_id: "default",
        threads: [firstThread],
      }),
    ]);

    unsubscribeFirst();
    unsubscribeSecond();
  });
});

function thread(overrides: Partial<ChatThread>): ChatThread {
  return {
    thread_id: "thread",
    runtime_session_id: "session",
    title: "Thread",
    agent_label: "chat",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-07-08T12:00:00.000Z",
    updated_at: "2026-07-08T12:00:00.000Z",
    ...overrides,
  };
}
