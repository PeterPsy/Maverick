import { useSyncExternalStore } from "react";

export type MaverickConnectionStatus = "checking" | "offline" | "online";
export type MaverickFreshness = "expired" | "fresh" | "unverified";
export type MaverickSyncState = "checking" | "error" | "idle" | "offline";

export type MaverickConnectivityState = {
  freshness: MaverickFreshness;
  lastSuccessfulAt: string | null;
  onlineActionsBlocked: boolean;
  source: "device" | "network";
  status: MaverickConnectionStatus;
  syncState: MaverickSyncState;
};

export const DEFAULT_MAVERICK_CONNECTIVITY_STATE: MaverickConnectivityState = {
  freshness: "unverified",
  lastSuccessfulAt: null,
  onlineActionsBlocked: false,
  source: "network",
  status: "online",
  syncState: "idle",
};

const LAST_SUCCESS_STORAGE_KEY = "maverick:pwa:last-success:v1";
const FRESH_WINDOW_MS = 24 * 60 * 60 * 1000;
const MAX_CLOCK_SKEW_MS = 5 * 60 * 1000;
const PROBE_TIMEOUT_MS = 4_000;
const listeners = new Set<() => void>();
let started = false;
let state = initialConnectivityState();

export function useMaverickConnectivity(): MaverickConnectivityState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function getMaverickConnectivitySnapshot(): MaverickConnectivityState {
  return state;
}

export function startConnectivityMonitoring(): void {
  if (started || typeof window === "undefined") {
    return;
  }
  started = true;
  window.addEventListener("offline", handleBrowserOffline);
  window.addEventListener("online", handleBrowserOnline);
  if (navigator.onLine === false) {
    setConnectionStatus("offline");
    return;
  }
  void verifyMaverickConnection();
}

export async function verifyMaverickConnection(): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }
  if (navigator.onLine === false) {
    setConnectionStatus("offline");
    return false;
  }
  setConnectionStatus("checking");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch("/api/pwa/config", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      setConnectionStatus("offline");
      return false;
    }
    recordMaverickNetworkSuccess();
    return true;
  } catch {
    setConnectionStatus("offline");
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
}

export function recordMaverickNetworkSuccess(at = new Date()): void {
  const timestamp = at.toISOString();
  try {
    window.localStorage.setItem(LAST_SUCCESS_STORAGE_KEY, timestamp);
  } catch {
    // Connectivity must not depend on persistent browser storage.
  }
  state = deriveConnectivityState("online", timestamp, at.getTime());
  emitChange();
}

export function recordMaverickNetworkFailure(): void {
  setConnectionStatus("offline");
}

export function deriveConnectivityState(
  status: MaverickConnectionStatus,
  lastSuccessfulAt: string | null,
  now = Date.now(),
  onlineActionsBlocked = status === "offline",
): MaverickConnectivityState {
  const lastSuccessMs = lastSuccessfulAt ? Date.parse(lastSuccessfulAt) : Number.NaN;
  const hasValidTimestamp = Number.isFinite(lastSuccessMs) && lastSuccessMs <= now + MAX_CLOCK_SKEW_MS;
  const freshness: MaverickFreshness = !hasValidTimestamp
    ? "unverified"
    : now - lastSuccessMs > FRESH_WINDOW_MS
      ? "expired"
      : "fresh";
  return {
    freshness,
    lastSuccessfulAt: hasValidTimestamp ? new Date(lastSuccessMs).toISOString() : null,
    onlineActionsBlocked,
    source: status === "offline" || onlineActionsBlocked ? "device" : "network",
    status,
    syncState: status === "online" ? "idle" : status === "checking" ? "checking" : "offline",
  };
}

export function formatLastSuccessfulSync(value: string | null, locale = "it-IT"): string {
  if (!value || !Number.isFinite(Date.parse(value))) {
    return "Mai verificata";
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function initialConnectivityState(): MaverickConnectivityState {
  let lastSuccessfulAt: string | null = null;
  try {
    lastSuccessfulAt = typeof window === "undefined" ? null : window.localStorage.getItem(LAST_SUCCESS_STORAGE_KEY);
  } catch {
    lastSuccessfulAt = null;
  }
  const status = typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "checking";
  return deriveConnectivityState(status, lastSuccessfulAt);
}

function setConnectionStatus(status: MaverickConnectionStatus): void {
  const onlineActionsBlocked = status === "online" ? false : status === "offline" || state.onlineActionsBlocked;
  state = deriveConnectivityState(status, state.lastSuccessfulAt, Date.now(), onlineActionsBlocked);
  emitChange();
}

function handleBrowserOffline(): void {
  setConnectionStatus("offline");
}

function handleBrowserOnline(): void {
  setConnectionStatus("checking");
  void verifyMaverickConnection();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): MaverickConnectivityState {
  return state;
}

function emitChange(): void {
  listeners.forEach((listener) => listener());
}
