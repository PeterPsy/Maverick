export const DEVICE_USE_REQUEST = "maverick.device-use.request.v1";

export type DeviceUseMode = "off" | "on" | "full";
export type DeviceUseConsentMode = "perAction" | "perTask";
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
  settings: {
    selectedApp: string;
    additionalApps: string[];
    consentMode: DeviceUseConsentMode;
  };
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
  settings: { selectedApp: "", additionalApps: [], consentMode: "perAction" },
};

export function parseNativeDeviceUseSnapshot(value: unknown): NativeDeviceUseSnapshot {
  if (!value || typeof value !== "object") throw new Error("Risposta Device Use non valida.");
  const raw = value as Record<string, unknown>;
  if (raw.available === false) return unavailableSnapshot;
  const phase = String(raw.phase || "");
  const mode = String(raw.mode || "off");
  const rawApps = raw.apps;
  const rawPermissions = raw.permissions;
  const rawSettings = raw.settings;
  if (raw.available !== true
      || !["idle", "connecting", "ready", "running", "stopped"].includes(phase)
      || !["off", "on", "full"].includes(mode)
      || !Array.isArray(rawApps)
      || !rawPermissions || typeof rawPermissions !== "object"
      || !rawSettings || typeof rawSettings !== "object") {
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
  const settings = rawSettings as Record<string, unknown>;
  const selectedApp = typeof settings.selected_app === "string" ? settings.selected_app : "";
  const additionalApps = Array.isArray(settings.additional_apps)
    ? settings.additional_apps.filter((item): item is string => typeof item === "string")
    : [];
  const consentMode = settings.consent_mode;
  if (selectedApp.length > 256 || additionalApps.length > 23
      || additionalApps.some((item) => !item || item.length > 256)
      || !["perAction", "perTask"].includes(String(consentMode))) {
    throw new Error("Risposta Device Use non valida.");
  }
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
    settings: {
      selectedApp,
      additionalApps,
      consentMode: consentMode as DeviceUseConsentMode,
    },
  };
}

type NativeDeviceUseOptions = {
  activationId?: string;
  ticket?: string;
  websocketPath?: string;
  mode?: Exclude<DeviceUseMode, "off">;
  selectedApp?: string;
  additionalApps?: string[];
  consentMode?: DeviceUseConsentMode;
  permission?: DeviceUsePermission;
};

export function requestNativeDeviceUse(
  action: "status" | "start" | "stop" | "configure" | "permission",
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
