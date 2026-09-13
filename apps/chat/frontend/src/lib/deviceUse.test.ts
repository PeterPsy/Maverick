// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import {
  compatibleDeviceUseProvider,
  parseNativeDeviceUseSnapshot,
  requestNativeDeviceUse,
} from "./deviceUse";

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

  it("selects the certified Astra profile instead of the raw Codex default", () => {
    const providers: ProviderItem[] = [
      {
        provider_id: "codex",
        label: "Codex",
        description: "Raw runtime engine",
        provider_role: "runtime_engine",
        status: "active",
        default_model_family: "gpt-5.6-sol",
      },
      {
        provider_id: "agentic:astra-binding",
        label: "Astra",
        description: "Certified profile",
        provider_role: "runtime_engine",
        status: "active",
        selectable: true,
        default_model_family: "gpt-6-astra",
        workspace_profile_binding_id: "astra-binding",
      },
    ];

    expect(compatibleDeviceUseProvider(providers)?.provider_id).toBe("agentic:astra-binding");
    expect(compatibleDeviceUseProvider(providers.slice(0, 1))).toBeNull();
  });
});
