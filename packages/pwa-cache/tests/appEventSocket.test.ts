import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connectAppEventSocket } from "../src/appEventSocket";

class Socket {
  static instances: Socket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  constructor(readonly url: string) { Socket.instances.push(this); }
  close() { this.onclose?.(); }
}

describe("live event recovery", () => {
  let dispose: (() => void) | undefined;
  beforeEach(() => {
    Socket.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", Socket);
    vi.stubGlobal("window", { location: { protocol: "https:", host: "maverick.test" } });
  });
  afterEach(() => { dispose?.(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("refreshes once on useful reconnection, not on an online hint or the first open", () => {
    const refresh = vi.fn();
    const event = vi.fn();
    dispose = connectAppEventSocket(event, refresh);
    const first = Socket.instances[0];
    expect(first.url).toBe("wss://maverick.test/api/apps/events/ws");
    first.onopen?.();
    expect(refresh).not.toHaveBeenCalled();
    first.close();
    vi.advanceTimersByTime(1_000);
    expect(refresh).not.toHaveBeenCalled();
    const second = Socket.instances[1];
    second.onopen?.(); second.onopen?.();
    expect(refresh).toHaveBeenCalledOnce();
    first.onmessage?.({ data: '{"late":true}' });
    second.onmessage?.({ data: '{"fresh":true}' });
    expect(event).toHaveBeenCalledExactlyOnceWith({ fresh: true });
  });

  it("also refreshes after an initial connection failure and backs off repeated failures", () => {
    const refresh = vi.fn();
    dispose = connectAppEventSocket(vi.fn(), refresh);
    Socket.instances[0].close();
    vi.advanceTimersByTime(1_000);
    Socket.instances[1].close();
    vi.advanceTimersByTime(1_999);
    expect(Socket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    Socket.instances[2].onopen?.();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("ignores late events and cancels reconnection after teardown", () => {
    const refresh = vi.fn();
    dispose = connectAppEventSocket(vi.fn(), refresh);
    Socket.instances[0].close();
    dispose();
    Socket.instances[0].onopen?.();
    vi.advanceTimersByTime(60_000);
    expect(Socket.instances).toHaveLength(1);
    expect(refresh).not.toHaveBeenCalled();
  });
});
