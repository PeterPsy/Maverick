import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import { providerSupportsDeviceUse } from "./useDeviceUse";

function provider(overrides: Partial<ProviderItem> = {}): ProviderItem {
  return {
    provider_id: "agentic:sol",
    label: "GPT-5.6 Sol",
    description: "Codex",
    provider_role: "runtime_engine",
    runtime_engine_id: "codex",
    status: "active",
    selectable: true,
    default_model_family: "gpt-5.6-sol",
    workspace_profile_binding_id: "binding-sol",
    ...overrides,
  };
}

describe("providerSupportsDeviceUse", () => {
  it("accepts any active Codex model profile", () => {
    expect(providerSupportsDeviceUse(provider())).toBe(true);
    expect(providerSupportsDeviceUse(provider({
      provider_id: "agentic:terra",
      default_model_family: "gpt-5.6-terra",
      workspace_profile_binding_id: "binding-terra",
    }))).toBe(true);
  });

  it("rejects a runtime that cannot carry the native Codex tool bridge", () => {
    expect(providerSupportsDeviceUse(provider({
      runtime_engine_id: "maverick-tool-loop",
      default_model_family: "glm-5.3-flash",
    }))).toBe(false);
  });
});
