export const DEVICE_USE_REQUEST = "maverick.device-use.request.v1";

export type NativeDeviceUseSnapshot = {
  available: boolean;
  active: boolean;
  activationId: string | null;
  phase: "idle" | "connecting" | "ready" | "running" | "stopped";
  notice: string;
};

export function parseNativeDeviceUseSnapshot(value: unknown): NativeDeviceUseSnapshot {
  if (!value || typeof value !== "object") throw new Error("Risposta Device Use non valida.");
  const raw = value as Record<string, unknown>;
  if (raw.available === false) {
    return { available: false, active: false, activationId: null, phase: "idle", notice: "" };
  }
  const phase = String(raw.phase || "");
  if (raw.available !== true || !["idle", "connecting", "ready", "running", "stopped"].includes(phase)) {
    throw new Error("Risposta Device Use non valida.");
  }
  const activationId = typeof raw.activation_id === "string" && /^[0-9a-f-]{36}$/.test(raw.activation_id)
    ? raw.activation_id
    : null;
  return {
    available: true,
    active: raw.active === true,
    activationId,
    phase: phase as NativeDeviceUseSnapshot["phase"],
    notice: typeof raw.notice === "string" ? raw.notice.slice(0, 1000) : "",
  };
}

export function requestNativeDeviceUse(
  action: "status" | "start" | "stop",
  options: { activationId?: string; ticket?: string; websocketPath?: string } = {},
): Promise<NativeDeviceUseSnapshot> {
  const origin = (window as unknown as { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__;
  if (!origin || window.parent === window) {
    return Promise.resolve(parseNativeDeviceUseSnapshot({ available: false }));
  }
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    const close = () => { clearTimeout(timer); channel.port1.close(); channel.port2.close(); };
    const timer = window.setTimeout(() => {
      close();
      reject(new Error("Connessione Device Use non disponibile."));
    }, action === "start" ? 20_000 : 5_000);
    channel.port1.onmessage = (event) => {
      close();
      if (event.data?.ok !== true) {
        reject(new Error("Richiesta Device Use negata dall'app Mac."));
        return;
      }
      try { resolve(parseNativeDeviceUseSnapshot(event.data.result)); } catch (error) { reject(error); }
    };
    window.parent.postMessage({
      type: DEVICE_USE_REQUEST,
      action,
      ...(action === "start" ? options : {}),
    }, origin, [channel.port2]);
  });
}
