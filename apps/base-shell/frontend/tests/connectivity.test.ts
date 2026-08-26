// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { deriveConnectivityState, formatLastSuccessfulSync } from "../src/connectivity";

describe("Maverick connectivity", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  });

  it("derives source and bounded freshness from the last confirmed sync", () => {
    const now = Date.parse("2026-08-26T12:00:00Z");
    const fresh = deriveConnectivityState("offline", "2026-08-26T11:00:00Z", now);
    const expired = deriveConnectivityState("offline", "2026-08-24T11:00:00Z", now);
    const unknown = deriveConnectivityState("offline", null, now);
    const future = deriveConnectivityState("offline", "2027-08-26T11:00:00Z", now);

    expect(fresh).toMatchObject({ freshness: "fresh", onlineActionsBlocked: true, source: "device", syncState: "offline" });
    expect(expired.freshness).toBe("expired");
    expect(unknown.freshness).toBe("unverified");
    expect(future).toMatchObject({ freshness: "unverified", lastSuccessfulAt: null });
    expect(formatLastSuccessfulSync(null)).toBe("Mai verificata");
  });

  it("does not restore online actions until a fresh Maverick probe succeeds", async () => {
    vi.resetModules();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    let resolveProbe: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { resolveProbe = resolve; })));
    const connectivity = await import("../src/connectivity");
    connectivity.startConnectivityMonitoring();
    expect(connectivity.getMaverickConnectivitySnapshot()).toMatchObject({ status: "offline", onlineActionsBlocked: true });

    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    window.dispatchEvent(new Event("online"));
    expect(connectivity.getMaverickConnectivitySnapshot()).toMatchObject({ status: "checking", onlineActionsBlocked: true });

    resolveProbe?.(new Response("{}", { status: 200 }));
    await Promise.resolve();
    await Promise.resolve();
    expect(connectivity.getMaverickConnectivitySnapshot()).toMatchObject({ status: "online", onlineActionsBlocked: false, source: "network" });
  });
});
