export const DEVICE_USE_REQUEST = "maverick.device-use.request.v1";

export type DeviceUseMode = "off" | "full";
export type DeviceUsePermission = "screen" | "accessibility" | "input";

export type NativeDeviceUseSnapshot = {
  available: boolean;
  active: boolean;
  activationId: string | null;
  mode: DeviceUseMode;
  phase: "idle" | "connecting" | "ready" | "running" | "stopped";
  notice: string;
  apps: Array<{ bundleId: string; name: string }>;
  permissions: Record<DeviceUsePermission, boolean>;
};

const unavailableSnapshot: NativeDeviceUseSnapshot = {
  available: false,
  active: false,
  activationId: null,
  mode: "off",
  phase: "idle",
  notice: "",
  apps: [],
  permissions: { screen: false, accessibility: false, input: false },
};

export function parseNativeDeviceUseSnapshot(value: unknown): NativeDeviceUseSnapshot {
  if (!value || typeof value !== "object") throw new Error("Risposta Device Use non valida.");
  const raw = value as Record<string, unknown>;
  if (raw.available === false) return unavailableSnapshot;
  const phase = String(raw.phase || "");
  const mode = String(raw.mode || "off");
  const rawApps = raw.apps;
  const rawPermissions = raw.permissions;
  if (raw.available !== true
      || !["idle", "connecting", "ready", "running", "stopped"].includes(phase)
      || !["off", "full"].includes(mode)
      || !Array.isArray(rawApps)
      || !rawPermissions || typeof rawPermissions !== "object") {
    throw new Error("Risposta Device Use non valida.");
  }
  const apps = rawApps.map((item) => {
    if (!item || typeof item !== "object") throw new Error("Risposta Device Use non valida.");
    const app = item as Record<string, unknown>;
    const bundleId = typeof app.bundle_id === "string" ? app.bundle_id : "";
    const name = typeof app.name === "string" ? app.name : "";
    if (!bundleId || bundleId.length > 256 || !name || name.length > 256) {
      throw new Error("Risposta Device Use non valida.");
    }
    return { bundleId, name };
  });
  const permissions = rawPermissions as Record<string, unknown>;
  const activationId = typeof raw.activation_id === "string" && /^[0-9a-f-]{36}$/.test(raw.activation_id)
    ? raw.activation_id
    : null;
  return {
    available: true,
    active: raw.active === true,
    activationId,
    mode: mode as DeviceUseMode,
    phase: phase as NativeDeviceUseSnapshot["phase"],
    notice: typeof raw.notice === "string" ? raw.notice.slice(0, 1000) : "",
    apps,
    permissions: {
      screen: permissions.screen === true,
      accessibility: permissions.accessibility === true,
      input: permissions.input === true,
    },
  };
}

type NativeDeviceUseOptions = {
  activationId?: string;
  ticket?: string;
  websocketPath?: string;
  mode?: Exclude<DeviceUseMode, "off">;
  permission?: DeviceUsePermission;
};

export function requestNativeDeviceUse(
  action: "status" | "start" | "stop" | "permission",
  options: NativeDeviceUseOptions = {},
): Promise<NativeDeviceUseSnapshot> {
  const origin = (window as unknown as { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__;
  if (!origin || window.parent === window) {
    return Promise.resolve(unavailableSnapshot);
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
    window.parent.postMessage({ type: DEVICE_USE_REQUEST, action, ...options }, origin, [channel.port2]);
  });
}
