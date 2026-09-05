import { registeredMaverickFrameOwner, type MaverickFrameScope } from "./iframePolicy";

export const LOCAL_RUNTIME_REQUEST = "maverick.local-runtime.request.v1";
type NativeHandler = { postMessage(value: unknown): Promise<unknown> };
export function localNativeHandler(): NativeHandler | undefined {
  return (window as unknown as { webkit?: { messageHandlers?: { maverickLocalRuntime?: NativeHandler } } })
    .webkit?.messageHandlers?.maverickLocalRuntime;
}

export class LocalRuntimeBroker {
  private disposed = false;
  private active = new Set<MessagePort>();
  constructor(private scope: MaverickFrameScope, private native = localNativeHandler()) {}

  handle = (event: MessageEvent) => {
    if (event.data?.type !== LOCAL_RUNTIME_REQUEST
        || registeredMaverickFrameOwner(event, this.scope) !== "chat") return;
    const port = event.ports.length === 1 ? event.ports[0] : null;
    if (!port) return;
    const { action, text } = event.data;
    if (this.disposed || this.active.size >= 8 || !["status", "start", "poll", "stop"].includes(action)
        || (action === "start" && (typeof text !== "string" || !text.trim() || text.length > 12000))) {
      port.postMessage({ ok: false }); port.close(); return;
    }
    if (!this.native) { port.postMessage({ ok: true, result: { available: false } }); port.close(); return; }
    // Construct an allowlisted envelope; a frame cannot supply native scope/config/path/token fields.
    const request = { action, ...(action === "start" ? { text } : {}),
      workspace: this.scope.workspaceId, generation: this.scope.sessionGeneration };
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
    void this.native?.postMessage({ action: "stop", workspace: this.scope.workspaceId,
      generation: this.scope.sessionGeneration }).catch(() => undefined);
  }
}
