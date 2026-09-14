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
    const mode = event.data?.mode;
    const startValid = action !== "start" || (
      typeof activationId === "string" && /^[0-9a-f-]{36}$/.test(activationId)
      && typeof ticket === "string" && ticket.length >= 32 && ticket.length <= 256
      && websocketPath === "/ws/device-use/executor"
      && ["on", "full"].includes(mode)
    );
    const configureValid = action !== "configure" || (
      typeof event.data?.selectedApp === "string"
      && event.data.selectedApp.length <= 256
      && Array.isArray(event.data?.additionalApps)
      && event.data.additionalApps.length <= 23
      && event.data.additionalApps.every((item: unknown) => typeof item === "string" && item.length <= 256)
      && ["perAction", "perTask"].includes(event.data?.consentMode)
    );
    const permissionValid = action !== "permission"
      || ["screen", "accessibility", "input"].includes(event.data?.permission);
    if (this.disposed || this.active.size >= 4
        || !["status", "start", "stop", "configure", "permission"].includes(action)
        || !startValid || !configureValid || !permissionValid) {
      port.postMessage({ ok: false }); port.close(); return;
    }
    if (!this.native) {
      port.postMessage({ ok: true, result: { available: false } }); port.close(); return;
    }
    const request = {
      action,
      workspace: this.scope.workspaceId,
      generation: this.scope.sessionGeneration,
      ...(action === "start" ? { activationId, ticket, websocketPath, mode } : {}),
      ...(action === "configure" ? {
        selectedApp: event.data.selectedApp,
        additionalApps: event.data.additionalApps,
        consentMode: event.data.consentMode,
      } : {}),
      ...(action === "permission" ? { permission: event.data.permission } : {}),
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
  }
}
