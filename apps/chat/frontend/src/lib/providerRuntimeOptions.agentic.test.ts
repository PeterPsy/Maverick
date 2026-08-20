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

function modelProvider(providerId: string, providerLabel: string, modelId: string, modelLabel: string): ProviderItem {
  return {
    provider_id: providerId,
    label: providerLabel,
    description: "Remote agentic model provider",
    kind: "hosted_api",
    provider_role: "model_provider",
    status: "active",
    default_model_family: modelId,
    model_options: [
      {
        model_id: modelId,
        label: modelLabel,
        description: null,
        default_reasoning_effort: "high",
        supported_reasoning_efforts: reasoningOptions,
      },
    ],
  };
}

function agenticProfile(
  providerId: string,
  modelId: string,
  rolloutStatus: AgenticProfileItem["rollout_status"] = "available",
): AgenticProfileItem {
  return {
    workspace_profile_binding_id: `binding-${providerId}`,
    definition_id: `profile-${providerId}`,
    definition_revision: "1",
    display_name: `${providerId} · ${modelId} · fake-data preview`,
    runtime_engine_id: "maverick-tool-loop",
    model_provider_id: providerId,
    model_id: modelId,
    rollout_status: rolloutStatus,
    enabled: true,
    is_default: false,
    certified: true,
    certificate: { effective_status: "active" },
    default_reasoning_effort: "high",
    supported_reasoning_efforts: reasoningOptions,
  };
}

describe("remote agentic provider runtime options", () => {
  it("makes certified previews selectable while excluding suspended profiles", () => {
    const modelId = "gemini-3.6-flash";
    const preview = agenticProfile("google-ai-studio", modelId, "preview");
    const suspended = agenticProfile("google-ai-studio", modelId, "suspended");
    suspended.workspace_profile_binding_id = "binding-suspended";
    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", "Google AI Studio", modelId, "Gemini 3.6 Flash"),
      ],
      agentic_profiles: {
        default_binding_id: null,
        items: [preview, suspended],
      },
    });

    expect(providers.filter((provider) => provider.workspace_profile_binding_id)).toHaveLength(1);
    expect(providers[0]?.workspace_profile_binding_id).toBe(preview.workspace_profile_binding_id);
  });

  it("fails closed for missing certification or a non-active certificate", () => {
    const modelId = "gemini-3.6-flash";
    const missingCertification = agenticProfile("google-ai-studio", modelId);
    missingCertification.workspace_profile_binding_id = "binding-missing-certification";
    delete missingCertification.certified;
    const inactiveCertificate = agenticProfile("google-ai-studio", modelId);
    inactiveCertificate.workspace_profile_binding_id = "binding-inactive-certificate";
    inactiveCertificate.certificate = { effective_status: "revoked" };
    const activeCertificate = agenticProfile("google-ai-studio", modelId);
    activeCertificate.workspace_profile_binding_id = "binding-active-certificate";
    activeCertificate.certificate = { effective_status: "active" };

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", "Google AI Studio", modelId, "Gemini 3.6 Flash"),
      ],
      agentic_profiles: {
        default_binding_id: null,
        items: [missingCertification, inactiveCertificate, activeCertificate],
      },
    });

    expect(providers.filter((provider) => provider.workspace_profile_binding_id)).toHaveLength(1);
    expect(providers[0]?.workspace_profile_binding_id).toBe(activeCertificate.workspace_profile_binding_id);
  });

  it("does not fall back to mutable model reasoning metadata", () => {
    const modelId = "gemini-3.6-flash";
    const profile = agenticProfile("google-ai-studio", modelId);
    delete profile.default_reasoning_effort;
    delete profile.supported_reasoning_efforts;

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", "Google AI Studio", modelId, "Gemini 3.6 Flash"),
      ],
      agentic_profiles: { default_binding_id: null, items: [profile] },
    });

    expect(providers[0]?.default_reasoning_effort).toBeNull();
    expect(providers[0]?.supported_reasoning_efforts).toEqual([]);
  });

  it("uses reasoning choices pinned on the certified agentic profiles", () => {
    const googleModelId = "gemini-3.6-flash";
    const openRouterModelId = "deepseek/deepseek-v4-flash";
    const payload: ProviderPayload = {
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", "Google AI Studio", googleModelId, "Gemini 3.6 Flash"),
        modelProvider("openrouter", "OpenRouter", openRouterModelId, "DeepSeek V4 Flash"),
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
      title: provider.label,
      subtitle: provider.description,
      defaultReasoning: provider.default_reasoning_effort,
      reasoning: provider.supported_reasoning_efforts?.map((option) => option.effort),
    }))).toEqual([
      {
        model: googleModelId,
        title: "Gemini 3.6 Flash",
        subtitle: "Google AI Studio",
        defaultReasoning: "high",
        reasoning: ["minimal", "low", "medium", "high"],
      },
      {
        model: openRouterModelId,
        title: "DeepSeek V4 Flash",
        subtitle: "OpenRouter",
        defaultReasoning: "high",
        reasoning: ["minimal", "low", "medium", "high"],
      },
    ]);
  });
});
