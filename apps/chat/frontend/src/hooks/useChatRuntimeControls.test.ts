import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import {
  effectiveNewChatReasoningEffort,
  genericAgenticRuntimeConfig,
} from "./useChatRuntimeControls";

function agenticProvider(overrides: Partial<ProviderItem> = {}): ProviderItem {
  return {
    provider_id: "google-agentic",
    label: "Gemini · 3.5 Pro",
    description: "Google agentic profile",
    provider_role: "runtime_engine",
    status: "active",
    default_model_family: "gemini-3.5-pro",
    workspace_profile_binding_id: "binding-google-gemini-35-pro",
    ...overrides,
  };
}

describe("genericAgenticRuntimeConfig", () => {
  it("uses the provider default before the controlled reasoning state settles", () => {
    expect(effectiveNewChatReasoningEffort("", "max")).toBe("max");
    expect(effectiveNewChatReasoningEffort("high", "max")).toBe("high");
  });

  it("preserves the selected profile binding and reasoning without a catalog agent", () => {
    expect(genericAgenticRuntimeConfig(agenticProvider(), "max")).toMatchObject({
      agent_id: "chat",
      runtime_mode: "agentic",
      title: "Gemini · 3.5 Pro",
      workspace_profile_binding_id: "binding-google-gemini-35-pro",
      reasoning_effort: "max",
    });
    expect(genericAgenticRuntimeConfig(agenticProvider(), "max")).not.toHaveProperty(
      "declared_remote_data_class",
    );
  });

  it("preserves Codex reasoning without adding a remote-data declaration", () => {
    expect(genericAgenticRuntimeConfig(agenticProvider({
      provider_id: "codex-agentic",
      label: "Codex · gpt-5.6-sol",
      workspace_profile_binding_id: "binding-codex-sol",
    }), "xhigh")).toMatchObject({
      workspace_profile_binding_id: "binding-codex-sol",
      reasoning_effort: "xhigh",
    });
  });

  it("does not turn a plain hosted provider into an agentic session", () => {
    expect(genericAgenticRuntimeConfig(agenticProvider({
      provider_role: "model_provider",
    }), "max")).toBeNull();
  });
});
