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
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    vi.stubGlobal("WebSocket", Socket);
    vi.stubGlobal("window", { location: { protocol: "https:", host: "maverick.test" } });
  });
  afterEach(() => { dispose?.(); vi.restoreAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals(); });

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

  it('shares a direct socket and pauses offline/hidden without retry churn', () => {
    const target = new EventTarget();
    const documentTarget = Object.assign(new EventTarget(), { hidden: false });
    const navigator = { onLine: true };
    vi.stubGlobal('document', documentTarget);
    vi.stubGlobal('navigator', navigator);
    vi.stubGlobal('window', Object.assign(target, { location: { protocol: 'https:', host: 'maverick.test' } }));
    const refresh = vi.fn();
    dispose = connectAppEventSocket(vi.fn(), refresh);
    const unsubscribe = connectAppEventSocket(vi.fn(), vi.fn());
    expect(Socket.instances).toHaveLength(1);
    Socket.instances[0].onopen?.();
    unsubscribe();
    documentTarget.hidden = true;
    documentTarget.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(120_000);
    expect(Socket.instances).toHaveLength(1);
    navigator.onLine = false;
    documentTarget.hidden = false;
    documentTarget.dispatchEvent(new Event('visibilitychange'));
    expect(Socket.instances).toHaveLength(1);
    navigator.onLine = true;
    target.dispatchEvent(new Event('online'));
    Socket.instances[1].onopen?.();
    target.dispatchEvent(new Event('online'));
    expect(Socket.instances).toHaveLength(2);
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('uses only the exact shell parent and workspace in embedded frames and resyncs once on resume', () => {
    const parent = {};
    const target = Object.assign(new EventTarget(), {
      parent, location: { protocol: 'https:', host: 'frame.test', origin: 'https://frame.test' },
      __MAVERICK_PLATFORM_ORIGIN__: 'https://shell.test',
      __MAVERICK_APP_FRAME_CONTEXT__: { app_id: 'sample', workspace_id: 'workspace' },
    });
    vi.stubGlobal('window', target);
    const refresh = vi.fn();
    const receive = vi.fn();
    dispose = connectAppEventSocket(receive, refresh);
    const send = (data: unknown, source = parent, origin = 'https://shell.test') => {
      target.dispatchEvent(Object.assign(new Event('message'), { data, source, origin }));
    };
    const payload = { type: 'maverick.app.event', event: { workspace_id: 'workspace', fresh: true } };
    send(payload, {}, 'https://shell.test');
    send(payload, parent, 'https://attacker.test');
    send({ ...payload, event: { workspace_id: 'different' } });
    expect(receive).not.toHaveBeenCalled();
    send(payload);
    expect(receive).toHaveBeenCalledExactlyOnceWith(payload.event);
    send({ type: 'maverick.app.visibility-changed', visible: false });
    send(payload);
    send({ type: 'maverick.app.events-resync' });
    vi.advanceTimersByTime(120_000);
    expect(Socket.instances).toHaveLength(0);
    expect(receive).toHaveBeenCalledOnce();
    expect(refresh).not.toHaveBeenCalled();
    send({ type: 'maverick.app.visibility-changed', visible: true });
    send({ type: 'maverick.app.visibility-changed', visible: true });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('waits for the resumed shell stream after document suspension, including an already hidden frame', () => {
    const parent = {};
    const documentTarget = Object.assign(new EventTarget(), { hidden: false });
    const target = Object.assign(new EventTarget(), {
      parent, location: { protocol: 'https:', host: 'frame.test', origin: 'https://frame.test' },
      __MAVERICK_PLATFORM_ORIGIN__: 'https://shell.test',
      __MAVERICK_APP_FRAME_CONTEXT__: { app_id: 'sample', workspace_id: 'workspace' },
    });
    vi.stubGlobal('window', target);
    vi.stubGlobal('document', documentTarget);
    const refresh = vi.fn();
    dispose = connectAppEventSocket(vi.fn(), refresh);
    const send = (data: unknown) => target.dispatchEvent(Object.assign(new Event('message'), {
      data, source: parent, origin: 'https://shell.test',
    }));
    send({ type: 'maverick.app.visibility-changed', visible: false });
    documentTarget.hidden = true;
    documentTarget.dispatchEvent(new Event('visibilitychange'));
    documentTarget.hidden = false;
    documentTarget.dispatchEvent(new Event('visibilitychange'));
    send({ type: 'maverick.app.visibility-changed', visible: true });
    vi.advanceTimersByTime(2000);
    expect(refresh).not.toHaveBeenCalled();
    send({ type: 'maverick.app.events-resync' });
    expect(refresh).toHaveBeenCalledOnce();
    expect(Socket.instances).toHaveLength(0);

    documentTarget.hidden = true;
    documentTarget.dispatchEvent(new Event('visibilitychange'));
    // Parent messages may arrive before this document's visibility event.
    send({ type: 'maverick.app.events-resync' });
    documentTarget.hidden = false;
    documentTarget.dispatchEvent(new Event('visibilitychange'));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
