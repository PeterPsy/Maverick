import { useSyncExternalStore } from "react";

export type TransportRecoverySignal = {
  kind: "confirmed" | "hint";
  revision: number;
};

const listeners = new Set<() => void>();
let signal: TransportRecoverySignal = { kind: "hint", revision: 0 };
let waitingForUsefulTransport = false;
let started = false;

export function useTransportRecoverySignal(): TransportRecoverySignal {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function getTransportRecoverySignal(): TransportRecoverySignal {
  return signal;
}

export function startTransportRecoveryMonitoring(): void {
  if (started || typeof window === "undefined") {
    return;
  }
  started = true;
  window.addEventListener("online", emitRetryHint);
  window.addEventListener("focus", emitRetryHint);
  document.addEventListener("visibilitychange", handleVisibilityChange);
}

export function recordMaverickTransportFailure(): void {
  waitingForUsefulTransport = true;
}

export function recordMaverickTransportResponse(): void {
  if (!waitingForUsefulTransport) {
    return;
  }
  waitingForUsefulTransport = false;
  emitSignal("confirmed");
}

export function resetTransportRecoveryScope(): void {
  waitingForUsefulTransport = false;
}

function handleVisibilityChange(): void {
  if (document.visibilityState === "visible") {
    emitRetryHint();
  }
}

function emitRetryHint(): void {
  emitSignal("hint");
}

function emitSignal(kind: TransportRecoverySignal["kind"]): void {
  signal = { kind, revision: signal.revision + 1 };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): TransportRecoverySignal {
  return signal;
}
