import { useSyncExternalStore } from "react";

export type ShellPwaUpdateState = {
  applying: boolean;
  available: boolean;
  buildId: string | null;
  recovery: "failed" | "idle" | "recovering" | "recovered";
};

const CONFIG_TIMEOUT_MS = 4_000;
const STATIC_CACHE_PREFIX = "maverick-static-v2:";
const KNOWN_STATIC_CACHES = new Set(["maverick-app-static-v2", "maverick-base-shell-v3"]);
const listeners = new Set<() => void>();
let waitingRegistration: ServiceWorkerRegistration | null = null;
let reloadOnControllerChange = false;
let lifecycleListenersInstalled = false;
let controlledWhenListenersInstalled = false;
let updateState: ShellPwaUpdateState = {
  applying: false,
  available: false,
  buildId: null,
  recovery: "idle",
};

export function registerShellServiceWorker(): void {
  if (!import.meta.env.PROD || typeof window === "undefined" || !("serviceWorker" in navigator)) {
    return;
  }

  const start = () => {
    configureShellServiceWorker().catch((error: unknown) => debugWarning("Maverick PWA setup failed.", error));
  };
  if (document.readyState === "complete") {
    void Promise.resolve().then(start);
  } else {
    window.addEventListener("load", start, { once: true });
  }
}

export function useShellPwaUpdate(): ShellPwaUpdateState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export async function applyShellServiceWorkerUpdate(): Promise<boolean> {
  const waiting = waitingRegistration?.waiting;
  if (!waiting) {
    return false;
  }
  reloadOnControllerChange = true;
  setUpdateState({ ...updateState, applying: true });
  waiting.postMessage({ type: "MAVERICK_SKIP_WAITING" });
  return true;
}

export function recoverShellStaticCache(): boolean {
  const controller = navigator.serviceWorker?.controller;
  if (!controller) {
    return false;
  }
  setUpdateState({ ...updateState, recovery: "recovering" });
  controller.postMessage({ type: "MAVERICK_RECOVER" });
  return true;
}

export async function disableShellServiceWorker(): Promise<void> {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(
    registrations
      .filter(isMaverickShellRegistration)
      .map(async (registration) => {
        for (const worker of [registration.installing, registration.waiting, registration.active]) {
          worker?.postMessage({ type: "MAVERICK_DISABLE" });
        }
        await registration.unregister();
      }),
  );
  if ("caches" in window) {
    const keys = await window.caches.keys();
    await Promise.all(
      keys
        .filter((key) => key.startsWith(STATIC_CACHE_PREFIX) || KNOWN_STATIC_CACHES.has(key))
        .map((key) => window.caches.delete(key)),
    );
  }
  waitingRegistration = null;
  setUpdateState({ applying: false, available: false, buildId: null, recovery: "idle" });
}

async function configureShellServiceWorker(): Promise<void> {
  const enabled = await serviceWorkerV2Enabled();
  if (enabled === false) {
    await disableShellServiceWorker();
    return;
  }
  if (enabled === null) {
    return;
  }
  installServiceWorkerLifecycleListeners();
  const registration = await navigator.serviceWorker.register("/sw.js", {
    scope: "/",
    updateViaCache: "none",
  });
  observeRegistration(registration);
  await registration.update().catch(() => undefined);
}

async function serviceWorkerV2Enabled(): Promise<boolean | null> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), CONFIG_TIMEOUT_MS);
  try {
    const response = await fetch("/api/pwa/config", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as { schema?: unknown; service_worker?: { enabled?: unknown; generation?: unknown } };
    if (payload.schema !== "maverick.pwa-config.v1" || payload.service_worker?.generation !== "v2") {
      return null;
    }
    return payload.service_worker.enabled === true;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeout);
  }
}

function installServiceWorkerLifecycleListeners(): void {
  if (lifecycleListenersInstalled) {
    return;
  }
  lifecycleListenersInstalled = true;
  controlledWhenListenersInstalled = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloadOnControllerChange || controlledWhenListenersInstalled) {
      reloadOnControllerChange = false;
      controlledWhenListenersInstalled = false;
      window.location.reload();
    }
  });
  navigator.serviceWorker.addEventListener("message", (event) => {
    const message = event.data && typeof event.data === "object" ? event.data as { build_id?: unknown; type?: unknown } : {};
    const buildId = typeof message.build_id === "string" ? message.build_id : null;
    if (message.type === "MAVERICK_SW_VERSION" && updateState.available) {
      setUpdateState({ ...updateState, buildId });
    } else if (message.type === "MAVERICK_SW_ACTIVATED") {
      setUpdateState({ ...updateState, applying: false, available: false, buildId, recovery: "idle" });
    } else if (message.type === "MAVERICK_SW_RECOVERED") {
      setUpdateState({ ...updateState, recovery: "recovered" });
    } else if (message.type === "MAVERICK_SW_RECOVERY_FAILED") {
      setUpdateState({ ...updateState, recovery: "failed" });
    }
  });
}

function observeRegistration(registration: ServiceWorkerRegistration): void {
  if (registration.waiting && navigator.serviceWorker.controller) {
    announceWaitingWorker(registration);
  }
  registration.addEventListener("updatefound", () => {
    const installing = registration.installing;
    installing?.addEventListener("statechange", () => {
      if (installing.state === "installed" && navigator.serviceWorker.controller && registration.waiting) {
        announceWaitingWorker(registration);
      }
    });
  });
}

function announceWaitingWorker(registration: ServiceWorkerRegistration): void {
  waitingRegistration = registration;
  setUpdateState({ ...updateState, applying: false, available: true, buildId: null });
  registration.waiting?.postMessage({ type: "MAVERICK_GET_VERSION" });
}

function isMaverickShellRegistration(registration: ServiceWorkerRegistration): boolean {
  const workers = [registration.installing, registration.waiting, registration.active].filter(Boolean) as ServiceWorker[];
  if (workers.some((worker) => new URL(worker.scriptURL).pathname === "/sw.js")) {
    return true;
  }
  return new URL(registration.scope).origin === window.location.origin && new URL(registration.scope).pathname === "/";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): ShellPwaUpdateState {
  return updateState;
}

function setUpdateState(next: ShellPwaUpdateState): void {
  updateState = next;
  listeners.forEach((listener) => listener());
}

function debugWarning(message: string, error: unknown): void {
  try {
    if (window.localStorage.getItem("maverick3:pwa-debug") === "1") {
      console.warn(message, error);
    }
  } catch {
    // Rendering and recovery never depend on diagnostics storage.
  }
}
