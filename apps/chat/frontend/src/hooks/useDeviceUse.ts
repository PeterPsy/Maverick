import { useCallback, useEffect, useRef, useState } from "react";
import {
  createDeviceUseActivation,
  getDeviceUseActivation,
  reconnectDeviceUseSession,
  stopDeviceUseActivation,
  type ChatThread,
  type DeviceUseActivation,
  type ProviderItem,
} from "../api/client";
import {
  requestNativeDeviceUse,
  type DeviceUseMode,
  type NativeDeviceUseSnapshot,
} from "../lib/deviceUse";
import { useDeviceUseThreadBinding } from "./useDeviceUseThreadBinding";

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

export function providerSupportsDeviceUse(provider: ProviderItem | null): provider is ProviderItem {
  const runtimeEngineId = provider?.runtime_engine_id || provider?.provider_id;
  return Boolean(
    provider
    && provider.provider_role === "runtime_engine"
    && runtimeEngineId === "codex"
    && Boolean(provider.workspace_profile_binding_id)
    && provider.selectable !== false
    && provider.status === "active"
  );
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
  isRuntimeBusy = false,
  provider,
  reasoningEffort,
  onPrepare,
  onReconnected,
}: {
  activeThread: ChatThread | null;
  isRuntimeBusy?: boolean;
  provider: ProviderItem | null;
  reasoningEffort: string;
  onPrepare: (providerId: string, reasoningEffort: string) => Promise<void> | void;
  onReconnected: (thread: ChatThread, activation: DeviceUseActivation) => void;
}) {
  const [snapshot, setSnapshot] = useState<NativeDeviceUseSnapshot>(emptySnapshot);
  const [activationId, setActivationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lease, setLease] = useState<{ id: string; ready: boolean } | null>(null);
  const { binding: threadBinding, error: bindingError } = useDeviceUseThreadBinding(activeThread);
  const threadBindingRef = useRef(threadBinding);
  threadBindingRef.current = threadBinding;
  const validatedLeaseRef = useRef<{ id: string; ready: boolean } | null>(null);
  const refreshSequenceRef = useRef(0);
  const activationRef = useRef<string | null>(null);
  activationRef.current = activationId;
  const threadRef = useRef(activeThread);
  threadRef.current = activeThread;
  const busyRef = useRef(false);
  const scope = `${activeThread?.thread_id || "draft"}:${threadBinding?.activation_id || activationId || ""}`;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  const pinnedMode = threadBinding?.mode === "full" || threadBinding?.mode === "on"
    ? threadBinding.mode : null;
  const reconnectMessage = useCallback(() => {
    if (activeThread?.device_use_enabled && !pinnedMode) {
      return bindingError || "Attendi il caricamento della modalità Device Use originale.";
    }
    if (pinnedMode === "on") {
      return "Questa chat usa la vecchia modalità limitata. Avvia una nuova chat e attiva PC use.";
    }
    return "Mac scollegato. Attiva PC use per ricollegare questa chat, poi invia il messaggio.";
  }, [activeThread?.device_use_enabled, bindingError, pinnedMode]);

  const refresh = useCallback(async () => {
    const sequence = ++refreshSequenceRef.current;
    const expectedScope = scopeRef.current;
    const id = threadRef.current?.device_use_enabled
      ? threadBindingRef.current?.activation_id
      : activationRef.current;
    const [native, core] = await Promise.allSettled([
      requestNativeDeviceUse("status"),
      id ? getDeviceUseActivation(id) : Promise.resolve(null),
    ]);
    const current = native.status === "fulfilled" ? native.value : emptySnapshot;
    if (sequence === refreshSequenceRef.current && scopeRef.current === expectedScope && !busyRef.current) {
      setSnapshot(current);
      const validated = id ? {
        id,
        ready: core.status === "fulfilled" && core.value?.ready === true
          && current.active && current.activationId === id,
      } : null;
      validatedLeaseRef.current = validated;
      setLease(validated);
    }
    return current;
  }, []);

  useEffect(() => {
    if (activeThread?.device_use_enabled) setActivationId(null);
  }, [activeThread?.device_use_enabled, activeThread?.thread_id]);

  useEffect(() => {
    setError(null);
    void refresh();
    const onVisible = () => { if (document.visibilityState !== "hidden") void refresh(); };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(onVisible, 10_000);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [isRuntimeBusy, refresh, scope]);

  const currentId = activeThread?.device_use_enabled ? threadBinding?.activation_id : activationId;
  const mode: DeviceUseMode = currentId && lease?.id === currentId && lease.ready
    ? pinnedMode || snapshot.mode
    : "off";
  // Even while disconnected, a Device Use conversation retains its capability
  // restrictions (attachments, skills, references and multi-agent stay disabled).
  const enabled = Boolean(activeThread?.device_use_enabled || activationId);
  const locked = Boolean(activeThread);

  const stopCurrent = useCallback(async () => {
    const current = activationRef.current || threadBinding?.activation_id || null;
    const [core, native] = await Promise.allSettled([
      current ? stopDeviceUseActivation(current) : Promise.resolve(null),
      requestNativeDeviceUse("stop"),
    ]);
    const coreStopped = core.status === "fulfilled" && core.value?.status === "stopped";
    const nativeStopped = native.status === "fulfilled" && !native.value.active;
    if (!coreStopped && !nativeStopped) {
      throw new Error("Impossibile disattivare PC use. Riprova o usa Interrompi PC use nel menu Maverick.");
    }
    if (native.status === "fulfilled") setSnapshot(native.value);
    setLease(null);
    validatedLeaseRef.current = null;
    refreshSequenceRef.current++;
    setActivationId(null);
  }, [threadBinding?.activation_id, activeThread?.thread_id]);

  const selectMode = useCallback(async (nextMode: DeviceUseMode) => {
    if (busyRef.current) return;
    busyRef.current = true;
    refreshSequenceRef.current++;
    setBusy(true);
    setError(null);
    try {
      if (nextMode === "off") {
        await stopCurrent();
        return;
      }
      if (nextMode !== "full") {
        throw new Error("PC use consente solo accesso completo. Avvia una nuova chat e attiva PC use.");
      }
      if (activeThread && (!activeThread.device_use_enabled || nextMode !== pinnedMode)) {
        throw new Error("La modalità è fissata per questa chat. Avvia una nuova chat per cambiarla.");
      }
      if (activeThread && isRuntimeBusy) {
        throw new Error("device_use_session_busy");
      }
      if (!activeThread && !providerSupportsDeviceUse(provider)) {
        throw new Error("Device Use richiede un modello Codex attivo.");
      }
      if (activationRef.current) await stopCurrent();
      if (!activeThread && provider) {
        const selectedEffort = reasoningEffort
          || provider.default_reasoning_effort
          || provider.supported_reasoning_efforts?.[0]?.effort
          || "";
        await onPrepare(provider.provider_id, selectedEffort);
      }
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
        let ready = await waitUntilReady(createdId);
        if (threadRef.current?.thread_id !== activeThread?.thread_id) {
          throw new Error("Chat cambiata durante la connessione. Riattiva Device Use nella chat desiderata.");
        }
        if (activeThread) {
          ready = await reconnectDeviceUseSession(
            activeThread.runtime_session_id, createdId, threadBinding!.activation_id,
          );
          onReconnected(activeThread, ready);
        } else {
          setActivationId(createdId);
        }
        setSnapshot(await requestNativeDeviceUse("status"));
        setLease({ id: createdId, ready: ready.ready });
      } catch (activationError) {
        void stopDeviceUseActivation(createdId).catch(() => undefined);
        void requestNativeDeviceUse("stop").catch(() => undefined);
        throw activationError;
      }
    } catch (activationError) {
      const message = activationError instanceof Error ? activationError.message : "Impossibile attivare Device Use.";
      setError(message === "device_use_reconnect_scope_changed"
        ? "Le impostazioni On sono diverse da quelle di questa chat. Ripristinale prima di ricollegarti, oppure avvia una nuova chat."
        : message === "device_use_session_busy"
          ? "Attendi la fine del turno o interrompilo prima di ricollegare il Mac."
          : message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [activeThread, isRuntimeBusy, onPrepare, onReconnected, pinnedMode, provider, reasoningEffort, stopCurrent, threadBinding]);

  const ensureReady = useCallback(async () => {
    if (busyRef.current) throw new Error("Attendi il completamento della connessione Device Use.");
    const expectedScope = scopeRef.current;
    const current = await refresh();
    if (expectedScope !== scopeRef.current) throw new Error("La chat è cambiata durante la verifica del Mac.");
    const id = threadRef.current?.device_use_enabled
      ? threadBindingRef.current?.activation_id
      : activationRef.current;
    if (!id || !current.active || current.activationId !== id
        || validatedLeaseRef.current?.id !== id || !validatedLeaseRef.current.ready) {
      throw new Error(reconnectMessage());
    }
  }, [reconnectMessage, refresh]);

  return {
    activationId,
    available: snapshot.available,
    busy,
    enabled,
    ensureReady,
    error: error || bindingError,
    locked,
    mode,
    pinnedMode,
    refresh,
    selectMode,
    snapshot,
  };
}
