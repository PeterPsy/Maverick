import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import { genericAgenticRuntimeConfig } from "./useChatRuntimeControls";

function agenticProvider(overrides: Partial<ProviderItem> = {}): ProviderItem {
  return {
    provider_id: "google-agentic",
    label: "Gemini · 3.5 Pro",
    description: "Google agentic profile",
    provider_role: "runtime_engine",
    status: "active",
    default_model_family: "gemini-3.5-pro",
    workspace_profile_binding_id: "binding-google-gemini-35-pro",
    requires_synthetic_data_declaration: true,
    ...overrides,
  };
}

describe("genericAgenticRuntimeConfig", () => {
  it("preserves the selected profile binding and reasoning without a catalog agent", () => {
    expect(genericAgenticRuntimeConfig(agenticProvider(), "max")).toMatchObject({
      agent_id: "chat",
      runtime_mode: "agentic",
      title: "Gemini · 3.5 Pro",
      workspace_profile_binding_id: "binding-google-gemini-35-pro",
      reasoning_effort: "max",
      declared_remote_data_class: "workspace_internal_fake",
    });
  });

  it("preserves Codex reasoning without adding a remote-data declaration", () => {
    expect(genericAgenticRuntimeConfig(agenticProvider({
      provider_id: "codex-agentic",
      label: "Codex · gpt-5.6-sol",
      workspace_profile_binding_id: "binding-codex-sol",
      requires_synthetic_data_declaration: false,
    }), "xhigh")).toMatchObject({
      workspace_profile_binding_id: "binding-codex-sol",
      reasoning_effort: "xhigh",
      declared_remote_data_class: undefined,
    });
  });

  it("does not turn a plain hosted provider into an agentic session", () => {
    expect(genericAgenticRuntimeConfig(agenticProvider({
      provider_role: "model_provider",
    }), "max")).toBeNull();
  });
});
