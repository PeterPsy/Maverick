import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import {
  effectiveNewChatReasoningEffort,
  genericAgenticRuntimeConfig,
  researchRuntimeConfig,
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

  it("builds Research as a clean full-access profile", () => {
    const provider = agenticProvider({
      runtime_engine_id: "maverick-tool-loop",
      execution_family: "maverick_agent",
      research_compatible: true,
      agentic_effective_tool_handle_mode: "all_currently_authorized",
      agentic_effective_capabilities: {
        status: "active",
        reason_code: null,
        snapshot_digest: "research-capabilities",
        execution_mode: "full-access",
        capabilities: {
          streaming: true,
          tool_orchestration: true,
          cli: true,
          mcp: true,
          skill_catalog: true,
          filesystem_list: true,
          filesystem_read: true,
          filesystem_write: true,
          shell: true,
          interrupt: true,
          same_turn_steering: true,
          recovery: true,
          confirmation_resume: true,
          provider_private_state: true,
          attachment_modalities: ["file"],
          app_references: true,
          confirmations: true,
        },
      },
    });

    expect(researchRuntimeConfig(provider, "high")).toEqual({
      agent_id: "research",
      agent_role_id: "",
      agent_type_id: "",
      runtime_mode: "agentic",
      runtime_profile: "research",
      requested_mode: "full-access",
      workspace_profile_binding_id: "binding-google-gemini-35-pro",
      reasoning_effort: "high",
      skill_catalog_app_id: "",
      skill_ids: [],
      skill_activation_mode: "explicit",
      source_app_id: "chat",
      system_prompt: "",
      title: "Research",
    });
  });

  it("builds the same Research profile for a compatible native model", () => {
    const provider = agenticProvider({
      provider_id: "codex",
      runtime_engine_id: "codex",
      execution_family: "native_agent",
      research_compatible: true,
      agentic_effective_capabilities: {
        status: "active",
        reason_code: null,
        snapshot_digest: "codex-research-capabilities",
        execution_mode: "full-access",
        capabilities: {
          streaming: true,
          tool_orchestration: true,
          cli: true,
          mcp: true,
          skill_catalog: true,
          filesystem_list: true,
          filesystem_read: true,
          filesystem_write: true,
          shell: true,
          interrupt: true,
          same_turn_steering: true,
          recovery: true,
          confirmation_resume: true,
          provider_private_state: true,
          attachment_modalities: ["file"],
          app_references: true,
          confirmations: true,
        },
      },
    });

    expect(researchRuntimeConfig(provider, "xhigh")).toMatchObject({
      agent_id: "research",
      runtime_profile: "research",
      requested_mode: "full-access",
      workspace_profile_binding_id: "binding-google-gemini-35-pro",
      reasoning_effort: "xhigh",
      system_prompt: "",
      skill_ids: [],
    });
  });
});
