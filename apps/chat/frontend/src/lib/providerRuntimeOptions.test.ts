import { describe, expect, it } from "vitest";
import type { AgenticProfileItem, ProviderPayload } from "../api/client";
import {
  initialProviderSelectionId,
  providerItemsFromPayload,
} from "./providerRuntimeOptions";

const capabilities = {
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
  same_turn_steering: false,
  recovery: true,
  confirmation_resume: true,
  provider_private_state: true,
  attachment_modalities: ["file"],
  app_references: true,
  confirmations: true,
};

const payload: ProviderPayload = {
  workspace_id: "default",
  active_provider: {
    provider_id: "codex",
    label: "Codex",
    description: "Agentic runtime",
    kind: "runtime_backend",
    provider_role: "runtime_engine",
    status: "active",
    default_model_family: "gpt-5.6-sol",
    model_options: [{
      model_id: "gpt-5.6-sol",
      label: "GPT-5.6-Sol",
      description: null,
      default_reasoning_effort: "xhigh",
      supported_reasoning_efforts: [
        { effort: "high", label: "High", description: null },
        { effort: "xhigh", label: "Extra high", description: null },
      ],
      input_modalities: ["text", "file"],
      output_modalities: ["text"],
    }],
  },
  hosted_text: {
    profile: "fast_model",
    active_provider: {
      provider_id: "openrouter",
      label: "OpenRouter",
      description: "Hosted API",
      kind: "hosted_api",
      provider_role: "model_provider",
      status: "active",
      default_model_family: "google/gemma-4-31b-it:free",
      model_options: [
        {
          model_id: "z-ai/glm-5.3-flash",
          label: "GLM 5.3 Flash",
          description: null,
          default_reasoning_effort: "max",
          supported_reasoning_efforts: [
            { effort: "max", label: "Maximum", description: null },
            { effort: "high", label: "High", description: null },
          ],
          input_modalities: ["text"],
          output_modalities: ["text"],
        },
        {
          model_id: "google/gemma-4-31b-it:free",
          label: "Gemma 4 31B (free)",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text", "image"],
          output_modalities: ["text"],
        },
        {
          model_id: "hexgrad/kokoro-82m",
          label: "Kokoro 82M",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text"],
          output_modalities: ["speech"],
        },
      ],
    },
    selection: null,
    model_settings: null,
    available_providers: [],
  },
};

function profile(overrides: Partial<AgenticProfileItem>): AgenticProfileItem {
  return {
    workspace_profile_binding_id: "binding-codex",
    definition_id: "profile-codex",
    display_name: "Codex profile",
    runtime_engine_id: "codex",
    model_provider_id: "codex",
    model_id: "gpt-5.6-sol",
    default_reasoning_effort: "xhigh",
    supported_reasoning_efforts: [
      { effort: "high", label: "High", description: null },
      { effort: "xhigh", label: "Extra high", description: null },
    ],
    enabled: true,
    is_default: true,
    selectable: true,
    execution_family: "native_agent",
    runtime_status: "complete",
    containment_status: "GO",
    effective_capabilities: {
      status: "active",
      reason_code: null,
      snapshot_digest: "fixture-capability-snapshot",
      capabilities,
    },
    ...overrides,
  } as AgenticProfileItem;
}

describe("provider runtime options", () => {
  it("maps direct agentic profiles to model choices", () => {
    const providers = providerItemsFromPayload({
      ...payload,
      agentic_profiles: {
        default_binding_id: "binding-codex",
        items: [profile({})],
      },
    });

    expect(providers).toHaveLength(1);
    expect(providers[0]).toMatchObject({
      provider_id: "codex",
      workspace_profile_binding_id: "binding-codex",
      default_model_family: "gpt-5.6-sol",
      label: "GPT-5.6-Sol",
      execution_family: "native_agent",
      default_reasoning_effort: "xhigh",
    });
  });

  it("uses the model label rather than API provider routing", () => {
    const providers = providerItemsFromPayload({
      ...payload,
      agentic_profiles: {
        default_binding_id: "binding-openrouter",
        items: [profile({
          workspace_profile_binding_id: "binding-openrouter",
          definition_id: "profile-openrouter",
          display_name: "OpenRouter GLM 5.3 Flash · Relace",
          runtime_engine_id: "maverick-tool-loop",
          model_provider_id: "openrouter",
          model_id: "z-ai/glm-5.3-flash",
          default_reasoning_effort: "max",
          supported_reasoning_efforts: [
            { effort: "max", label: "Maximum", description: null },
            { effort: "high", label: "High", description: null },
          ],
          execution_family: "maverick_agent",
        })],
      },
    });

    expect(providers).toHaveLength(1);
    expect(providers[0].label).toBe("GLM 5.3 Flash");
    expect(providers[0].label).not.toContain("Relace");
  });

  it("does not expose text-only or speech models as composer choices", () => {
    const providers = providerItemsFromPayload(payload);

    expect(providers.map((provider) => provider.label)).toEqual(["Codex"]);
    expect(providers.some((provider) => provider.execution_family === "hosted_text")).toBe(false);
    expect(providers.some((provider) => provider.hosted_model_id === "hexgrad/kokoro-82m")).toBe(false);
  });

  it("never accepts a plain hosted provider as a new model selection", () => {
    const hosted = payload.hosted_text!.active_provider!;

    expect(initialProviderSelectionId(null, [hosted])).toBe("");
    expect(initialProviderSelectionId(hosted.provider_id, [hosted])).toBe("");
  });
});
