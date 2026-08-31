// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";

describe("transport recovery signals", () => {
  afterEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("treats browser events only as retry hints", async () => {
    const recovery = await import("../src/transportRecovery");
    const initial = recovery.getTransportRecoverySignal().revision;
    recovery.startTransportRecoveryMonitoring();

    window.dispatchEvent(new Event("online"));
    window.dispatchEvent(new Event("focus"));

    expect(recovery.getTransportRecoverySignal().revision).toBe(initial + 2);
  });

  it("wakes pending work after another Maverick response", async () => {
    const recovery = await import("../src/transportRecovery");
    const initial = recovery.getTransportRecoverySignal().revision;

    recovery.recordMaverickTransportFailure();
    recovery.recordMaverickTransportResponse();
    recovery.recordMaverickTransportResponse();

    expect(recovery.getTransportRecoverySignal().revision).toBe(initial + 1);
  });
});
