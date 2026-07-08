/**
 * @vitest-environment happy-dom
 */
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../api/client";
import { resetRuntimeThreadSourceForTests } from "./runtimeThreadSource";
import { useRuntimeThreads } from "./useRuntimeThreads";

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

function RuntimeThreadsProbe({ onError, onThreads }: { onError: (error: string | null) => void; onThreads?: (threads: ChatThread[]) => void }) {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [error, setError] = useState<string | null>(null);

  useRuntimeThreads({ setError, setThreads });

  useEffect(() => {
    onError(error);
  }, [error, onError]);
  useEffect(() => {
    onThreads?.(threads);
  }, [onThreads, threads]);

  return null;
}

describe("useRuntimeThreads", () => {
  let container: HTMLDivElement;
  let root: Root;
  let originalBroadcastChannel: typeof BroadcastChannel | undefined;
  let originalWebSocket: typeof WebSocket | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    resetRuntimeThreadSourceForTests();
    MockWebSocket.instances = [];
    originalBroadcastChannel = globalThis.BroadcastChannel;
    originalWebSocket = globalThis.WebSocket;
    globalThis.BroadcastChannel = undefined as unknown as typeof BroadcastChannel;
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    globalThis.BroadcastChannel = originalBroadcastChannel as typeof BroadcastChannel;
    globalThis.WebSocket = originalWebSocket as typeof WebSocket;
    resetRuntimeThreadSourceForTests();
    vi.useRealTimers();
  });

  it("does not reconnect after authorization or missing-route close codes", async () => {
    const onError = vi.fn();
    await act(async () => {
      root.render(<RuntimeThreadsProbe onError={onError} />);
    });

    expect(MockWebSocket.instances).toHaveLength(1);

    await act(async () => {
      MockWebSocket.instances[0].onclose?.({ code: 4401 } as CloseEvent);
      vi.advanceTimersByTime(30000);
    });

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(onError).toHaveBeenLastCalledWith("Runtime thread stream is not authorized.");
  });

  it("backs off reconnect attempts after transient closes", async () => {
    await act(async () => {
      root.render(<RuntimeThreadsProbe onError={() => undefined} />);
    });

    expect(MockWebSocket.instances).toHaveLength(1);

    await act(async () => {
      MockWebSocket.instances[0].onclose?.({ code: 1006 } as CloseEvent);
      vi.advanceTimersByTime(499);
    });
    expect(MockWebSocket.instances).toHaveLength(1);

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    await act(async () => {
      MockWebSocket.instances[1].onclose?.({ code: 1006 } as CloseEvent);
      vi.advanceTimersByTime(999);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it("applies delta thread changes without a full catalog replacement", async () => {
    const onThreads = vi.fn();
    await act(async () => {
      root.render(<RuntimeThreadsProbe onError={() => undefined} onThreads={onThreads} />);
    });
    const firstThread = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "First" });
    const secondThread = thread({
      thread_id: "thread-2",
      runtime_session_id: "session-2",
      title: "Second",
      created_at: "2026-06-29T00:00:01.000Z",
      updated_at: "2026-06-29T00:00:01.000Z",
    });

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({ type: "runtime.thread.snapshot", workspace_id: "default", threads: [firstThread], at: "2026-06-29T00:00:00.000Z" }),
      } as MessageEvent);
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({ type: "runtime.thread.changed", workspace_id: "default", action: "created", thread: secondThread }),
      } as MessageEvent);
    });

    expect(onThreads).toHaveBeenLastCalledWith([secondThread, firstThread]);

    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          type: "runtime.thread.changed",
          workspace_id: "default",
          action: "deleted",
          deleted_thread_ids: ["thread-1"],
        }),
      } as MessageEvent);
    });

    expect(onThreads).toHaveBeenLastCalledWith([secondThread]);
  });

  it("shares one WebSocket across multiple hook subscribers in one frame", async () => {
    const firstThreads = vi.fn();
    const secondThreads = vi.fn();
    await act(async () => {
      root.render(
        <>
          <RuntimeThreadsProbe onError={() => undefined} onThreads={firstThreads} />
          <RuntimeThreadsProbe onError={() => undefined} onThreads={secondThreads} />
        </>,
      );
    });

    expect(MockWebSocket.instances).toHaveLength(1);

    const firstThread = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "First" });
    await act(async () => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({ type: "runtime.thread.snapshot", workspace_id: "default", threads: [firstThread], at: "2026-06-29T00:00:00.000Z" }),
      } as MessageEvent);
    });

    expect(firstThreads).toHaveBeenLastCalledWith([firstThread]);
    expect(secondThreads).toHaveBeenLastCalledWith([firstThread]);
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
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-06-29T00:00:00.000Z",
    updated_at: "2026-06-29T00:00:00.000Z",
    ...overrides,
  };
}
