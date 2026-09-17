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

const googleAgenticReasoningOptions: ProviderReasoningOption[] = [
  { effort: "high", label: "High", description: null },
];

const openRouterAgenticReasoningOptions: ProviderReasoningOption[] = [
  { effort: "max", label: "Maximum", description: null },
  { effort: "high", label: "High", description: null },
  { effort: "low", label: "Low", description: null },
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
  runtimeStatus = "complete",
  supportedReasoningEfforts: ProviderReasoningOption[] = reasoningOptions,
  defaultReasoningEffort = "high",
): AgenticProfileItem {
  return {
    workspace_profile_binding_id: `binding-${providerId}`,
    definition_id: `profile-${providerId}`,
    display_name: `${providerId} · ${modelId} · fake-data preview`,
    runtime_engine_id: "maverick-tool-loop",
    model_provider_id: providerId,
    model_id: modelId,
    enabled: true,
    is_default: false,
    selectable: true,
    execution_family: "maverick_agent",
    runtime_status: runtimeStatus,
    containment_status: "GO",
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
    default_reasoning_effort: defaultReasoningEffort,
    supported_reasoning_efforts: supportedReasoningEfforts,
  };
}

describe("remote agentic provider runtime options", () => {
  it("maps one current model config directly into the composer", () => {
    const modelId = "gpt-5.6-sol";
    const profile = agenticProfile("codex", modelId);
    profile.workspace_profile_binding_id = "binding-codex-sol";
    profile.definition_id = "profile-codex-sol";
    profile.runtime_engine_id = "codex";
    profile.execution_family = "native_agent";

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("codex", "Codex", modelId, "GPT-5.6-Sol"),
      ],
      agentic_profiles: {
        default_binding_id: null,
        items: [profile],
      },
    });

    expect(providers).toHaveLength(1);
    expect(providers[0]?.workspace_profile_binding_id).toBe("binding-codex-sol");
    expect(providers[0]?.profile_detail).toBe("Runtime: codex · Model: codex/gpt-5.6-sol");
  });

  it("does not hide duplicate workspace configs returned by the server", () => {
    const first = agenticProfile("openrouter", "z-ai/glm-5.3-flash");
    first.workspace_profile_binding_id = "binding-openrouter-first";
    const second = {
      ...first,
      workspace_profile_binding_id: "binding-openrouter-second",
      definition_id: "profile-openrouter-second",
    };

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [],
      agentic_profiles: {
        default_binding_id: null,
        items: [first, second],
      },
    });

    expect(providers.map((provider) => provider.workspace_profile_binding_id)).toEqual([
      "binding-openrouter-first",
      "binding-openrouter-second",
    ]);
  });

  it("uses the runtime id for the directly configured default", () => {
    const modelId = "gpt-6-astra";
    const configuredDefault = agenticProfile("codex", modelId);
    configuredDefault.workspace_profile_binding_id = "binding-codex-astra";
    configuredDefault.definition_id = "profile-codex-astra-default";
    configuredDefault.runtime_engine_id = "codex";
    configuredDefault.execution_family = "native_agent";
    configuredDefault.is_default = true;

    const providers = providerItemsFromPayload({
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("codex", "Codex", modelId, "GPT-6-Astra"),
      ],
      agentic_profiles: {
        default_binding_id: configuredDefault.workspace_profile_binding_id,
        items: [configuredDefault],
      },
    });

    expect(providers).toHaveLength(1);
    expect(providers[0]?.provider_id).toBe("codex");
    expect(providers[0]?.workspace_profile_binding_id).toBe(
      configuredDefault.workspace_profile_binding_id,
    );
  });

  it("uses the server selectable projection while excluding unavailable configs", () => {
    const modelId = "gemini-3.6-flash";
    const preview = agenticProfile("google-ai-studio", modelId);
    const suspended = agenticProfile("google-ai-studio", modelId, "incomplete");
    suspended.workspace_profile_binding_id = "binding-suspended";
    suspended.selectable = false;
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
    const contained = agenticProfile("google-ai-studio", "gemini-3.6-flash");
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

  it("fails closed for unavailable, non-selectable, or missing effective profiles", () => {
    const modelId = "gemini-3.6-flash";
    const unavailable = agenticProfile("google-ai-studio", modelId);
    unavailable.workspace_profile_binding_id = "binding-unavailable";
    unavailable.runtime_status = "incomplete";
    unavailable.selectable = false;
    const nonSelectable = agenticProfile("google-ai-studio", modelId);
    nonSelectable.workspace_profile_binding_id = "binding-not-selectable";
    nonSelectable.selectable = false;
    const activeProfile = agenticProfile("google-ai-studio", modelId);
    activeProfile.workspace_profile_binding_id = "binding-active";
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
        items: [unavailable, nonSelectable, missingEffectiveSnapshot, activeProfile],
      },
    });

    expect(providers.filter((provider) => provider.workspace_profile_binding_id)).toHaveLength(1);
    expect(providers[0]?.workspace_profile_binding_id).toBe(activeProfile.workspace_profile_binding_id);
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

  it("uses reasoning choices declared by the agentic profiles", () => {
    const googleModelId = "gemini-3.6-flash";
    const openRouterModelId = "z-ai/glm-5.3-flash";
    const payload: ProviderPayload = {
      workspace_id: "default",
      active_provider: null,
      available_providers: [
        modelProvider("google-ai-studio", "Google AI Studio", googleModelId, "Gemini 3.6 Flash"),
        modelProvider("openrouter", "OpenRouter", openRouterModelId, "GLM 5.3 Flash"),
      ],
      agentic_profiles: {
        default_binding_id: null,
        items: [
          agenticProfile(
            "google-ai-studio",
            googleModelId,
            "complete",
            googleAgenticReasoningOptions,
          ),
          agenticProfile(
            "openrouter",
            openRouterModelId,
            "complete",
            openRouterAgenticReasoningOptions,
            "max",
          ),
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
        reasoning: ["high"],
      },
      {
        model: openRouterModelId,
        title: "openrouter · z-ai/glm-5.3-flash · fake-data preview",
        subtitle: "OpenRouter",
        defaultReasoning: "max",
        reasoning: ["max", "high", "low"],
      },
    ]);
  });
});
