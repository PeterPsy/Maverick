import { useCallback, useEffect, useRef, useState } from "react";
import {
  createDeviceUseActivation,
  getDeviceUseActivation,
  stopDeviceUseActivation,
  type ChatThread,
  type ProviderItem,
} from "../api/client";
import { requestNativeDeviceUse } from "../lib/deviceUse";

const REQUIRED_MODEL = "gpt-6-astra";
const REQUIRED_EFFORT = "high";

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
  const [available, setAvailable] = useState(false);
  const [activationId, setActivationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activationRef = useRef<string | null>(null);
  activationRef.current = activationId;

  useEffect(() => {
    let current = true;
    void requestNativeDeviceUse("status").then((snapshot) => {
      if (!current) return;
      setAvailable(snapshot.available);
      if (snapshot.active && snapshot.activationId) {
        void getDeviceUseActivation(snapshot.activationId).then((activation) => {
          if (current && !activation.bound) setActivationId(snapshot.activationId);
        }).catch(() => undefined);
      }
    }).catch(() => {
      if (current) setAvailable(false);
    });
    return () => {
      current = false;
      void requestNativeDeviceUse("stop").catch(() => undefined);
    };
  }, []);

  useEffect(() => {
    // Once Core has materialized the Device Use thread, the activation is no
    // longer reusable authority for another new chat. The native socket stays
    // alive and the persisted thread remains the source of truth.
    if (activeThread?.device_use_enabled) setActivationId(null);
  }, [activeThread?.device_use_enabled]);

  const enabled = activeThread
    ? Boolean(activeThread.device_use_enabled)
    : Boolean(activationId);
  const locked = Boolean(activeThread);

  const toggle = useCallback(async () => {
    if (busy || locked) return;
    setBusy(true);
    setError(null);
    if (activationRef.current) {
      const current = activationRef.current;
      setActivationId(null);
      await Promise.allSettled([
        stopDeviceUseActivation(current),
        requestNativeDeviceUse("stop"),
      ]);
      setBusy(false);
      return;
    }
    const provider = compatibleProvider(providers);
    if (!provider) {
      setError("Device Use richiede il profilo Codex gpt-6-astra con effort High.");
      setBusy(false);
      return;
    }
    let createdId = "";
    try {
      await onPrepare(provider.provider_id, REQUIRED_EFFORT);
      const activation = await createDeviceUseActivation(crypto.randomUUID());
      createdId = activation.activation_id;
      if (!activation.ticket || activation.websocket_path !== "/ws/device-use/executor") {
        throw new Error("Attivazione Device Use incompleta.");
      }
      const native = await requestNativeDeviceUse("start", {
        activationId: createdId,
        ticket: activation.ticket,
        websocketPath: activation.websocket_path,
      });
      if (!native.available) throw new Error("Device Use è disponibile solo nell'app Maverick per macOS.");
      await waitUntilReady(createdId);
      setActivationId(createdId);
    } catch (activationError) {
      if (createdId) void stopDeviceUseActivation(createdId).catch(() => undefined);
      void requestNativeDeviceUse("stop").catch(() => undefined);
      setError(activationError instanceof Error ? activationError.message : "Impossibile attivare Device Use.");
    } finally {
      setBusy(false);
    }
  }, [busy, locked, onPrepare, providers]);

  return { activationId, available, busy, enabled, error, locked, toggle };
}
