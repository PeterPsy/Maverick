import { useCallback, useEffect, useRef, useState } from "react";
import {
  createDeviceUseActivation,
  getDeviceUseActivation,
  stopDeviceUseActivation,
  type ChatThread,
  type ProviderItem,
} from "../api/client";
import {
  requestNativeDeviceUse,
  type DeviceUseConsentMode,
  type DeviceUseMode,
  type DeviceUsePermission,
  type NativeDeviceUseSnapshot,
} from "../lib/deviceUse";

const REQUIRED_MODEL = "gpt-6-astra";
const REQUIRED_EFFORT = "high";

const emptySnapshot: NativeDeviceUseSnapshot = {
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

function compatibleProvider(providers: ProviderItem[]): ProviderItem | null {
  return providers.find((provider) => (
    provider.provider_role === "runtime_engine"
    && provider.default_model_family === REQUIRED_MODEL
    && Boolean(provider.workspace_profile_binding_id)
    && provider.selectable !== false
    && provider.status === "active"
  )) || null;
}

async function waitUntilReady(activationId: string) {
  const deadline = performance.now() + 10_000;
  while (performance.now() < deadline) {
    const activation = await getDeviceUseActivation(activationId);
    if (activation.ready) return activation;
    if (["offline", "stopped", "expired"].includes(activation.status)) {
      throw new Error(activation.reason || "L'executor Mac non è disponibile.");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  throw new Error("Connessione al Mac scaduta.");
}

export function useDeviceUse({
  activeThread,
  providers,
  onPrepare,
}: {
  activeThread: ChatThread | null;
  providers: ProviderItem[];
  onPrepare: (providerId: string, reasoningEffort: string) => Promise<void> | void;
}) {
  const [snapshot, setSnapshot] = useState<NativeDeviceUseSnapshot>(emptySnapshot);
  const [activationId, setActivationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stoppedThreadId, setStoppedThreadId] = useState<string | null>(null);
  const activationRef = useRef<string | null>(null);
  activationRef.current = activationId;

  const refresh = useCallback(async () => {
    try {
      const current = await requestNativeDeviceUse("status");
      setSnapshot(current);
      return current;
    } catch {
      setSnapshot(emptySnapshot);
      return emptySnapshot;
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!activeThread?.device_use_enabled) setStoppedThreadId(null);
    if (activeThread?.device_use_enabled) setActivationId(null);
  }, [activeThread?.device_use_enabled, activeThread?.thread_id]);

  const threadMode = activeThread?.device_use?.mode === "full" ? "full" : "on";
  const mode: DeviceUseMode = activeThread?.device_use_enabled
    ? (stoppedThreadId === activeThread.thread_id ? "off" : threadMode)
    : activationId ? snapshot.mode : "off";
  const enabled = mode !== "off";
  const locked = Boolean(activeThread);

  const stopCurrent = useCallback(async () => {
    const current = activationRef.current || activeThread?.device_use?.activation_id || null;
    setActivationId(null);
    if (activeThread?.thread_id) setStoppedThreadId(activeThread.thread_id);
    await Promise.allSettled([
      ...(current ? [stopDeviceUseActivation(current)] : []),
      requestNativeDeviceUse("stop").then(setSnapshot),
    ]);
  }, [activeThread?.device_use?.activation_id, activeThread?.thread_id]);

  const selectMode = useCallback(async (nextMode: DeviceUseMode) => {
    if (busy || nextMode === mode) return;
    setBusy(true);
    setError(null);
    try {
      if (nextMode === "off") {
        await stopCurrent();
        return;
      }
      if (activeThread) {
        throw new Error("La modalità è fissata per questa chat. Avvia una nuova chat per riattivarla o cambiarla.");
      }
      const provider = compatibleProvider(providers);
      if (!provider) throw new Error("Device Use richiede il profilo Codex gpt-6-astra con effort High.");
      if (activationRef.current) await stopCurrent();
      await onPrepare(provider.provider_id, REQUIRED_EFFORT);
      const activation = await createDeviceUseActivation(crypto.randomUUID());
      const createdId = activation.activation_id;
      if (!activation.ticket || activation.websocket_path !== "/ws/device-use/executor") {
        throw new Error("Attivazione Device Use incompleta.");
      }
      try {
        const native = await requestNativeDeviceUse("start", {
          activationId: createdId,
          ticket: activation.ticket,
          websocketPath: activation.websocket_path,
          mode: nextMode,
        });
        if (!native.available) throw new Error("Device Use è disponibile solo nell'app Maverick per macOS.");
        await waitUntilReady(createdId);
        setSnapshot(native);
        setActivationId(createdId);
      } catch (activationError) {
        void stopDeviceUseActivation(createdId).catch(() => undefined);
        void requestNativeDeviceUse("stop").catch(() => undefined);
        throw activationError;
      }
    } catch (activationError) {
      setError(activationError instanceof Error ? activationError.message : "Impossibile attivare Device Use.");
    } finally {
      setBusy(false);
    }
  }, [activeThread, busy, mode, onPrepare, providers, stopCurrent]);

  const configure = useCallback(async (settings: {
    selectedApp: string;
    additionalApps: string[];
    consentMode: DeviceUseConsentMode;
  }) => {
    if (busy || enabled) return;
    setBusy(true); setError(null);
    try {
      setSnapshot(await requestNativeDeviceUse("configure", settings));
    } catch (settingsError) {
      setError(settingsError instanceof Error ? settingsError.message : "Impossibile salvare le impostazioni.");
      throw settingsError;
    } finally { setBusy(false); }
  }, [busy, enabled]);

  const requestPermission = useCallback(async (permission: DeviceUsePermission) => {
    if (busy || enabled) return;
    setBusy(true); setError(null);
    try {
      setSnapshot(await requestNativeDeviceUse("permission", { permission }));
      window.setTimeout(() => { void refresh(); }, 600);
    } catch (permissionError) {
      setError(permissionError instanceof Error ? permissionError.message : "Permesso non disponibile.");
    } finally { setBusy(false); }
  }, [busy, enabled, refresh]);

  return {
    activationId,
    available: snapshot.available,
    busy,
    configure,
    enabled,
    error,
    locked,
    mode,
    refresh,
    requestPermission,
    selectMode,
    snapshot,
  };
}
