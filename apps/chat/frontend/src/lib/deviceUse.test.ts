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
      mode: "full", phase: "ready", notice: "ok", ticket: "secret",
      apps: [{ bundle_id: "com.apple.Notes", name: "Note", private: "discard" }],
      permissions: { screen: true, accessibility: false, input: true, other: true },
      settings: { selected_app: "com.apple.Notes", additional_apps: [], consent_mode: "perTask" },
    })).toEqual({
      available: true, active: true, activationId: "01234567-89ab-cdef-0123-456789abcdef",
      mode: "full", phase: "ready", notice: "ok",
      apps: [{ bundleId: "com.apple.Notes", name: "Note" }],
      permissions: { screen: true, accessibility: false, input: true },
      settings: { selectedApp: "com.apple.Notes", additionalApps: [], consentMode: "perTask" },
    });
  });

  it("rejects unrecognized native phases", () => {
    expect(() => parseNativeDeviceUseSnapshot({ available: true, phase: "shell" })).toThrow();
  });

  it("does not impose an application discovery count ceiling for Full", () => {
    const apps = Array.from({ length: 300 }, (_, index) => ({
      bundle_id: `com.example.App${index}`,
      name: `App ${index}`,
    }));
    expect(parseNativeDeviceUseSnapshot({
      available: true,
      active: true,
      activation_id: "01234567-89ab-cdef-0123-456789abcdef",
      mode: "full",
      phase: "ready",
      notice: "",
      apps,
      permissions: { screen: true, accessibility: true, input: true },
      settings: { selected_app: "", additional_apps: [], consent_mode: "perAction" },
    }).apps).toHaveLength(300);
  });
});
