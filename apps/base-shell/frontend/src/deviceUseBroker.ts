import { registeredMaverickFrameOwner, type MaverickFrameScope } from "./iframePolicy";

export const DEVICE_USE_REQUEST = "maverick.device-use.request.v1";
type NativeHandler = { postMessage(value: unknown): Promise<unknown> };

export function deviceUseNativeHandler(): NativeHandler | undefined {
  return (window as unknown as {
    webkit?: { messageHandlers?: { maverickDeviceUse?: NativeHandler } };
  }).webkit?.messageHandlers?.maverickDeviceUse;
}

export class DeviceUseBroker {
  private disposed = false;
  private active = new Set<MessagePort>();

  constructor(private scope: MaverickFrameScope, private native = deviceUseNativeHandler()) {}

  handle = (event: MessageEvent) => {
    if (event.data?.type !== DEVICE_USE_REQUEST
        || registeredMaverickFrameOwner(event, this.scope) !== "chat") return;
    const port = event.ports.length === 1 ? event.ports[0] : null;
    if (!port) return;
    const action = event.data?.action;
    const activationId = event.data?.activationId;
    const ticket = event.data?.ticket;
    const websocketPath = event.data?.websocketPath;
    const startValid = action !== "start" || (
      typeof activationId === "string" && /^[0-9a-f-]{36}$/.test(activationId)
      && typeof ticket === "string" && ticket.length >= 32 && ticket.length <= 256
      && websocketPath === "/ws/device-use/executor"
    );
    if (this.disposed || this.active.size >= 4 || !["status", "start", "stop"].includes(action) || !startValid) {
      port.postMessage({ ok: false }); port.close(); return;
    }
    if (!this.native) {
      port.postMessage({ ok: true, result: { available: false } }); port.close(); return;
    }
    const request = {
      action,
      workspace: this.scope.workspaceId,
      generation: this.scope.sessionGeneration,
      ...(action === "start" ? { activationId, ticket, websocketPath } : {}),
    };
    this.active.add(port);
    void this.native.postMessage(request).then((result) => {
      if (!this.disposed && this.active.has(port)) port.postMessage({ ok: true, result });
    }, () => {
      if (!this.disposed && this.active.has(port)) port.postMessage({ ok: false });
    }).finally(() => { this.active.delete(port); port.close(); });
  };

  dispose() {
    this.disposed = true;
    for (const port of this.active) port.close();
    this.active.clear();
    void this.native?.postMessage({
      action: "stop",
      workspace: this.scope.workspaceId,
      generation: this.scope.sessionGeneration,
    }).catch(() => undefined);
  }
}
