// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocalRuntimeBroker, LOCAL_RUNTIME_REQUEST } from "./localRuntimeBroker";
import { setMaverickFrameOrigin } from "./iframePolicy";

const scope = { workspaceId: "default", sessionGeneration: "login-1" };
afterEach(() => { document.body.innerHTML = ""; });
function request(owner = "chat", generation = "login-1", action = "status") {
  const frame = document.createElement("iframe"); document.body.append(frame);
  setMaverickFrameOrigin(frame, "https://chat-frame.example", owner, { ...scope, sessionGeneration: generation });
  const port = { postMessage: vi.fn(), close: vi.fn() };
  const event = new MessageEvent("message", { data: { type: LOCAL_RUNTIME_REQUEST, action, text: "hello", workspace: "evil", path: "/auth.json" },
    source: frame.contentWindow, origin: "https://chat-frame.example", ports: [port as unknown as MessagePort] });
  return { event, port };
}
describe("native local runtime broker", () => {
  it("accepts exact registered Chat scope and strips caller scope/paths", async () => {
    const native = { postMessage: vi.fn(async () => ({ available: true })) };
    const broker = new LocalRuntimeBroker(scope, native);
    const { event, port } = request("chat", "login-1", "start"); broker.handle(event);
    await Promise.resolve(); await Promise.resolve();
    expect(native.postMessage).toHaveBeenCalledWith({ action: "start", text: "hello", workspace: "default", generation: "login-1" });
    expect(port.postMessage).toHaveBeenCalledWith({ ok: true, result: { available: true } });
    broker.dispose();
  });
  it("rejects foreign owner, old login, forged origin and unknown actions", () => {
    const native = { postMessage: vi.fn(async () => ({})) };
    const broker = new LocalRuntimeBroker(scope, native);
    broker.handle(request("storage").event); broker.handle(request("chat", "old").event);
    const { event } = request();
    broker.handle(new MessageEvent("message", { origin: "https://evil.example", data: event.data, ports: [...event.ports], source: event.source }));
    broker.handle(request("chat", "login-1", "shell").event);
    expect(native.postMessage).not.toHaveBeenCalled();
  });
  it("closes replies and stops native work on logout", async () => {
    let complete!: (value: unknown) => void;
    const native = { postMessage: vi.fn(() => new Promise((resolve) => { complete = resolve; })) };
    const broker = new LocalRuntimeBroker(scope, native);
    const { event, port } = request(); broker.handle(event);
    const finish = complete;
    broker.dispose(); finish({ messages: ["private"] });
    await Promise.resolve();
    expect(port.postMessage).not.toHaveBeenCalled(); expect(port.close).toHaveBeenCalled();
    expect(native.postMessage).toHaveBeenLastCalledWith({ action: "stop", workspace: "default", generation: "login-1" });
  });
});
