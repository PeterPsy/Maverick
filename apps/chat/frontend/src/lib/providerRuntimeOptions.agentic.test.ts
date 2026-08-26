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
    selectable: true,
    containment_status: "GO",
    certified: true,
    certificate: { effective_status: "active" },
    effective_capabilities: {
      status: "active",
      reason_code: null,
      snapshot_digest: "fixture-capability-snapshot",
      capabilities: {
        streaming: true,
        tool_orchestration: true,
        cli: false,
        mcp: false,
        skill_catalog: false,
        filesystem_list: true,
        filesystem_read: true,
        filesystem_write: false,
        shell: false,
        interrupt: true,
        same_turn_steering: false,
        recovery: true,
        confirmation_resume: true,
        provider_private_state: true,
        attachment_modalities: [],
        app_references: false,
        confirmations: true,
      },
    },
    default_reasoning_effort: "high",
    supported_reasoning_efforts: reasoningOptions,
  };
}

describe("remote agentic provider runtime options", () => {
  it("uses the server selectable projection while excluding suspended profiles", () => {
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
    expect(providers[0]?.label).toBe(preview.display_name);
  });

  it("does not offer a contained remote profile even when legacy fields look active", () => {
    const contained = agenticProfile("google-ai-studio", "gemini-3.6-flash", "preview");
    contained.selectable = false;
    contained.containment_status = "NO-GO";
    contained.containment_reason = "hosted_agent_runtime_disabled";

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [],
      agentic_profiles: { default_binding_id: null, items: [contained] },
    });

    expect(providers.some((provider) => provider.workspace_profile_binding_id === contained.workspace_profile_binding_id)).toBe(false);
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
    const missingEffectiveSnapshot = agenticProfile("google-ai-studio", modelId);
    missingEffectiveSnapshot.workspace_profile_binding_id = "binding-missing-effective";
    delete missingEffectiveSnapshot.effective_capabilities;

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", "Google AI Studio", modelId, "Gemini 3.6 Flash"),
      ],
      agentic_profiles: {
        default_binding_id: null,
        items: [missingCertification, inactiveCertificate, missingEffectiveSnapshot, activeCertificate],
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
        title: "google-ai-studio · gemini-3.6-flash · fake-data preview",
        subtitle: "Google AI Studio",
        defaultReasoning: "high",
        reasoning: ["minimal", "low", "medium", "high"],
      },
      {
        model: openRouterModelId,
        title: "openrouter · deepseek/deepseek-v4-flash · fake-data preview",
        subtitle: "OpenRouter",
        defaultReasoning: "high",
        reasoning: ["minimal", "low", "medium", "high"],
      },
    ]);
  });
});
