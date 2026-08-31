// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { disableShellServiceWorker, recoverShellStaticCache, storageFileCacheFeatureEnabled } from "../src/pwa";
import { shellCacheLifecycle } from "../src/pwaCacheRuntime";

describe("PWA client recovery", () => {
  const originalServiceWorker = Object.getOwnPropertyDescriptor(navigator, "serviceWorker");
  const originalCaches = Object.getOwnPropertyDescriptor(window, "caches");

  afterEach(() => {
    if (originalServiceWorker) Object.defineProperty(navigator, "serviceWorker", originalServiceWorker);
    else delete (navigator as { serviceWorker?: unknown }).serviceWorker;
    if (originalCaches) Object.defineProperty(window, "caches", originalCaches);
    else delete (window as { caches?: unknown }).caches;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("unregisters the shell worker and deletes only known static caches", async () => {
    const postMessage = vi.fn();
    const unregister = vi.fn().mockResolvedValue(true);
    const deleted: string[] = [];
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: {
        controller: { postMessage },
        getRegistrations: vi.fn().mockResolvedValue([
          {
            active: { postMessage, scriptURL: "https://maverick.test/sw.js" },
            installing: null,
            scope: "https://maverick.test/",
            unregister,
            waiting: null,
          },
        ]),
      },
    });
    Object.defineProperty(window, "caches", {
      configurable: true,
      value: {
        delete: vi.fn(async (name: string) => { deleted.push(name); return true; }),
        keys: vi.fn().mockResolvedValue([
          "maverick-static-v2:one",
          "maverick-app-static-v2",
          "maverick-base-shell-v3",
          "mail-private-cache",
        ]),
      },
    });

    await disableShellServiceWorker();

    expect(postMessage).toHaveBeenCalledWith({ type: "MAVERICK_DISABLE" });
    expect(unregister).toHaveBeenCalledOnce();
    expect(deleted.sort()).toEqual(["maverick-app-static-v2", "maverick-base-shell-v3", "maverick-static-v2:one"].sort());
  });

  it("requests an in-place verified cache recovery from the active worker", () => {
    const postMessage = vi.fn();
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { controller: { postMessage } },
    });

    expect(recoverShellStaticCache()).toBe(true);
    expect(postMessage).toHaveBeenCalledWith({ type: "MAVERICK_RECOVER" });
  });

  it("enables the Storage broker only for the exact v2 boolean projection", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        schema: "maverick.pwa-config.v2",
        features: { storage_file_cache: true },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        schema: "maverick.pwa-config.v2",
        features: { storage_file_cache: "true" },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response("not-json", { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockRejectedValueOnce(new TypeError("transport unavailable"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(storageFileCacheFeatureEnabled()).resolves.toBe(true);
    await expect(storageFileCacheFeatureEnabled()).resolves.toBe(false);
    await expect(storageFileCacheFeatureEnabled()).resolves.toBe(false);
    await expect(storageFileCacheFeatureEnabled()).resolves.toBe(false);
    await expect(storageFileCacheFeatureEnabled()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/pwa/config", expect.objectContaining({
      cache: "no-store",
      credentials: "same-origin",
    }));
  });

  it("fails closed and clears private cache authority on an authenticated config rejection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure")
      .mockResolvedValue({ pendingCleanupCount: 0, removed: 0, status: "complete" });

    await expect(storageFileCacheFeatureEnabled()).resolves.toBe(false);

    expect(cleanup).toHaveBeenCalledOnce();
  });
});
