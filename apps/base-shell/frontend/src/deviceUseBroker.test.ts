// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeviceUseBroker, DEVICE_USE_REQUEST } from "./deviceUseBroker";
import { setMaverickFrameOrigin } from "./iframePolicy";

const scope = { workspaceId: "default", sessionGeneration: "login-1" };
afterEach(() => { document.body.innerHTML = ""; });

function request(action = "status", extras: Record<string, unknown> = {}) {
  const frame = document.createElement("iframe"); document.body.append(frame);
  setMaverickFrameOrigin(frame, "https://chat-frame.example", "chat", scope);
  const port = { postMessage: vi.fn(), close: vi.fn() };
  return {
    event: new MessageEvent("message", {
      data: { type: DEVICE_USE_REQUEST, action, ...extras }, source: frame.contentWindow,
      origin: "https://chat-frame.example", ports: [port as unknown as MessagePort],
    }),
    port,
  };
}

describe("Device Use broker", () => {
  it("adds the trusted scope and forwards only the allowlisted activation", async () => {
    const native = { postMessage: vi.fn(async () => ({ available: true, phase: "connecting" })) };
    const broker = new DeviceUseBroker(scope, native);
    const { event } = request("start", {
      activationId: "01234567-89ab-cdef-0123-456789abcdef",
      ticket: "t".repeat(64), websocketPath: "/ws/device-use/executor", mode: "full", path: "/private",
    });
    broker.handle(event); await Promise.resolve(); await Promise.resolve();
    expect(native.postMessage).toHaveBeenCalledWith({
      action: "start", activationId: "01234567-89ab-cdef-0123-456789abcdef",
      ticket: "t".repeat(64), websocketPath: "/ws/device-use/executor",
      mode: "full",
      workspace: "default", generation: "login-1",
    });
  });

  it("forwards only bounded native settings fields", async () => {
    const native = { postMessage: vi.fn(async () => ({ available: true, phase: "idle" })) };
    const broker = new DeviceUseBroker(scope, native);
    const { event } = request("configure", {
      selectedApp: "com.apple.Notes",
      additionalApps: ["com.apple.TextEdit"],
      consentMode: "perTask",
      privateValue: "discarded",
    });
    broker.handle(event); await Promise.resolve(); await Promise.resolve();
    expect(native.postMessage).toHaveBeenCalledWith({
      action: "configure",
      selectedApp: "com.apple.Notes",
      additionalApps: ["com.apple.TextEdit"],
      consentMode: "perTask",
      workspace: "default",
      generation: "login-1",
    });
  });

  it("does not expose the bridge outside the native host", () => {
    const broker = new DeviceUseBroker(scope, undefined);
    const { event, port } = request(); broker.handle(event);
    expect(port.postMessage).toHaveBeenCalledWith({ ok: true, result: { available: false } });
  });
});
