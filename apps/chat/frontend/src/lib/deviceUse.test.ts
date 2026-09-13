// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { parseNativeDeviceUseSnapshot, requestNativeDeviceUse } from "./deviceUse";

describe("Device Use native protocol", () => {
  it("is unavailable in the webapp without the positive native bridge", async () => {
    expect(await requestNativeDeviceUse("status")).toMatchObject({ available: false });
  });

  it("projects only bounded public native state", () => {
    expect(parseNativeDeviceUseSnapshot({
      available: true, active: true, activation_id: "01234567-89ab-cdef-0123-456789abcdef",
      phase: "ready", notice: "ok", ticket: "secret",
    })).toEqual({
      available: true, active: true, activationId: "01234567-89ab-cdef-0123-456789abcdef",
      phase: "ready", notice: "ok",
    });
  });

  it("rejects unrecognized native phases", () => {
    expect(() => parseNativeDeviceUseSnapshot({ available: true, phase: "shell" })).toThrow();
  });
});
