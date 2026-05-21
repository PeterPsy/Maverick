/**
 * @vitest-environment happy-dom
 */
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../api/client";
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

function RuntimeThreadsProbe({ onError }: { onError: (error: string | null) => void }) {
  const [, setThreads] = useState<ChatThread[]>([]);
  const [error, setError] = useState<string | null>(null);

  useRuntimeThreads({ setError, setThreads });

  useEffect(() => {
    onError(error);
  }, [error, onError]);

  return null;
}

describe("useRuntimeThreads", () => {
  let container: HTMLDivElement;
  let root: Root;
  let originalWebSocket: typeof WebSocket | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    originalWebSocket = globalThis.WebSocket;
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
    globalThis.WebSocket = originalWebSocket as typeof WebSocket;
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
});
