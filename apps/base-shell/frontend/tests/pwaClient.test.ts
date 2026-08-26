// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { disableShellServiceWorker, recoverShellStaticCache } from "../src/pwa";

describe("PWA client recovery", () => {
  const originalServiceWorker = Object.getOwnPropertyDescriptor(navigator, "serviceWorker");
  const originalCaches = Object.getOwnPropertyDescriptor(window, "caches");

  afterEach(() => {
    if (originalServiceWorker) Object.defineProperty(navigator, "serviceWorker", originalServiceWorker);
    else delete (navigator as { serviceWorker?: unknown }).serviceWorker;
    if (originalCaches) Object.defineProperty(window, "caches", originalCaches);
    else delete (window as { caches?: unknown }).caches;
    vi.restoreAllMocks();
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
});
