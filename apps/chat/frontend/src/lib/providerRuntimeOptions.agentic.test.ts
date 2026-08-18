import { describe, expect, it } from "vitest";
import type {
  AgenticProfileItem,
  ProviderItem,
  ProviderPayload,
  ProviderReasoningOption,
} from "../api/client";
import { providerItemsFromPayload } from "./providerRuntimeOptions";

const reasoningOptions: ProviderReasoningOption[] = [
  { effort: "minimal", label: "Minimal", description: null },
  { effort: "low", label: "Low", description: null },
  { effort: "medium", label: "Medium", description: null },
  { effort: "high", label: "High", description: null },
];

function modelProvider(providerId: string, modelId: string): ProviderItem {
  return {
    provider_id: providerId,
    label: providerId,
    description: "Remote agentic model provider",
    kind: "hosted_api",
    provider_role: "model_provider",
    status: "active",
    default_model_family: modelId,
    model_options: [
      {
        model_id: modelId,
        label: modelId,
        description: null,
        default_reasoning_effort: "medium",
        supported_reasoning_efforts: reasoningOptions,
      },
    ],
  };
}

function agenticProfile(providerId: string, modelId: string): AgenticProfileItem {
  return {
    workspace_profile_binding_id: `binding-${providerId}`,
    definition_id: `profile-${providerId}`,
    definition_revision: "1",
    display_name: `${providerId} · ${modelId} · fake-data preview`,
    runtime_engine_id: "maverick-tool-loop",
    model_provider_id: providerId,
    model_id: modelId,
    rollout_status: "preview",
    enabled: true,
    is_default: false,
    certified: true,
  };
}

describe("remote agentic provider runtime options", () => {
  it("inherits reasoning choices exposed by Google and OpenRouter model metadata", () => {
    const googleModelId = "gemini-3.6-flash";
    const openRouterModelId = "deepseek/deepseek-v4-flash";
    const payload: ProviderPayload = {
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", googleModelId),
        modelProvider("openrouter", openRouterModelId),
      ],
      agentic_profiles: {
        default_binding_id: null,
        items: [
          agenticProfile("google-ai-studio", googleModelId),
          agenticProfile("openrouter", openRouterModelId),
        ],
      },
    };

    const providers = providerItemsFromPayload(payload);

    expect(providers.map((provider) => ({
      model: provider.default_model_family,
      defaultReasoning: provider.default_reasoning_effort,
      reasoning: provider.supported_reasoning_efforts?.map((option) => option.effort),
    }))).toEqual([
      {
        model: googleModelId,
        defaultReasoning: "medium",
        reasoning: ["minimal", "low", "medium", "high"],
      },
      {
        model: openRouterModelId,
        defaultReasoning: "medium",
        reasoning: ["minimal", "low", "medium", "high"],
      },
    ]);
  });
});
