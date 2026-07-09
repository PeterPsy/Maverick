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
  await Promise.resolve();
  await Promise.resolve();
}

describe("RuntimeThreadSource", () => {
  let originalBroadcastChannel: typeof BroadcastChannel | undefined;
  let originalWebSocket: typeof WebSocket | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
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
    vi.useRealTimers();
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
