import type {
  AgenticProfileItem,
  HostedTextProviderStatus,
  ProviderItem,
  ProviderPayload,
  ProviderReasoningOption,
} from "../api/client";
import type { AgentRuntimeConfig } from "../hooks/useMessageSubmission";

export function providerItemsFromPayload(payload: ProviderPayload): ProviderItem[] {
  const options: ProviderItem[] = [];
  const agenticProfiles = (payload.agentic_profiles?.items || []).filter(
    (profile) =>
      profile.enabled &&
      profile.certified === true &&
      (profile.rollout_status === "preview" || profile.rollout_status === "available") &&
      profile.certificate?.effective_status === "active",
  );
  if (agenticProfiles.length) {
    options.push(
      ...agenticProfiles.map((profile) => {
        const engine = [payload.active_provider, ...(payload.available_providers || [])].find(
          (provider) => provider?.provider_id === profile.runtime_engine_id,
        );
        const modelProvider = providerForAgenticProfile(payload, profile);
        const model = modelProvider?.model_options?.find((candidate) => candidate.model_id === profile.model_id);
        const reasoning = reasoningForAgenticProfile(payload, profile);
        return {
          ...(engine || {
            description: "Pinned agentic runtime profile",
            label: model?.label || profile.model_id,
            status: "active",
            default_model_family: profile.model_id,
          }),
          provider_id: profile.is_default
            ? profile.runtime_engine_id
            : `agentic:${encodeURIComponent(profile.workspace_profile_binding_id)}`,
          provider_role: "runtime_engine",
          workspace_profile_binding_id: profile.workspace_profile_binding_id,
          default_model_family: profile.model_id,
          label: model?.label || profile.model_id,
          description: modelProvider?.label || profile.model_provider_id,
          status: "active",
          agentic_rollout_status: profile.rollout_status,
          agentic_certificate_status: profile.certificate?.effective_status || null,
          agentic_certificate_expires_at: profile.certificate?.expires_at || null,
          agentic_egress_policy_id: profile.egress_policy_id || null,
          agentic_allowed_tool_handles: profile.allowed_tool_handles || [],
          agentic_max_estimated_cost_microusd: profile.max_estimated_cost_microusd ?? null,
          requires_synthetic_data_declaration: false,
          default_reasoning_effort: reasoning.defaultEffort,
          supported_reasoning_efforts: reasoning.options,
        };
      }),
    );
  } else if (payload.active_provider && providerIsActive(payload.active_provider)) {
    options.push(payload.active_provider);
  }

  const hostedProviders = hostedTextProviders(payload.hosted_text);
  if (hostedProviders.length) {
    options.push(...hostedProviders.flatMap((provider) => hostedModelProviderItems(payload.hosted_text, provider)));
  }

  if (!options.length) {
    options.push(...(payload.items || payload.available_providers || []).filter(providerIsSelectable));
  }

  return dedupeProviders(options);
}

function reasoningForAgenticProfile(
  _payload: ProviderPayload,
  profile: AgenticProfileItem,
): { defaultEffort: string | null; options: ProviderReasoningOption[] } {
  const options = profile.supported_reasoning_efforts || [];
  const requestedDefault = profile.default_reasoning_effort || null;
  const defaultEffort = options.length && !options.some((option) => option.effort === requestedDefault)
    ? options[0]?.effort || null
    : requestedDefault;
  return { defaultEffort, options };
}

function providerForAgenticProfile(
  payload: ProviderPayload,
  profile: AgenticProfileItem,
): ProviderItem | undefined {
  return [
    payload.active_provider,
    ...(payload.available_providers || []),
    ...(payload.items || []),
    payload.hosted_text?.active_provider,
    ...(payload.hosted_text?.available_providers || []),
  ].find((candidate) => candidate?.provider_id === profile.model_provider_id) || undefined;
}

export function providerUsesPlainHostedRuntime(provider: ProviderItem | null | undefined): boolean {
  return provider?.provider_role === "model_provider" && provider.kind === "hosted_api";
}

export function hostedProviderRuntimeConfig(provider: ProviderItem | null | undefined): AgentRuntimeConfig | null {
  if (!providerUsesPlainHostedRuntime(provider)) {
    return null;
  }
  if (!provider) {
    return null;
  }
  return {
    agent_id: "chat",
    agent_role_id: "",
    agent_type_id: "",
    runtime_mode: "plain_hosted_chat",
    routing_profile: "fast_model",
    hosted_provider_id: provider.hosted_provider_id || provider.provider_id,
    hosted_model_id: provider.hosted_model_id || provider.default_model_family || "",
    skill_catalog_app_id: "",
    skill_ids: [],
    skill_activation_mode: "explicit",
    source_app_id: "chat",
    system_prompt: "",
    title: provider?.label || "Hosted chat",
  };
}

function hostedTextProviders(status: HostedTextProviderStatus | null | undefined): ProviderItem[] {
  const providers = [
    status?.active_provider,
    ...(status?.available_providers || []),
  ].filter((provider): provider is ProviderItem => Boolean(provider) && providerIsSelectable(provider as ProviderItem));
  return dedupeProviders(providers);
}

function hostedModelProviderItems(status: HostedTextProviderStatus | null | undefined, provider: ProviderItem): ProviderItem[] {
  const activeProviderId = status?.active_provider?.provider_id || "";
  const selectedModelId =
    activeProviderId === provider.provider_id
      ? status?.model_settings?.selected_model_id || provider.default_model_family || ""
      : provider.default_model_family || "";
  const models =
    activeProviderId === provider.provider_id && status?.model_settings?.available_models?.length
      ? status.model_settings.available_models
      : provider.model_options || [];
  const textModels = models.filter(modelSupportsPlainHostedChat);
  if (models.length && !textModels.length) {
    return [];
  }
  const sortedModels = [...textModels].sort((left, right) => {
    if (left.model_id === selectedModelId) {
      return -1;
    }
    if (right.model_id === selectedModelId) {
      return 1;
    }
    return left.label.localeCompare(right.label);
  });
  if (!sortedModels.length) {
    return [
      {
        ...provider,
        provider_id: hostedRuntimeOptionId(provider.provider_id, selectedModelId || provider.default_model_family || "default"),
        hosted_provider_id: provider.provider_id,
        hosted_model_id: selectedModelId || provider.default_model_family || "",
        label: selectedModelId || "Hosted model",
        description: provider.label || provider.provider_id,
      },
    ];
  }
  return sortedModels.map((model) => ({
    ...provider,
    provider_id: hostedRuntimeOptionId(provider.provider_id, model.model_id),
    hosted_provider_id: provider.provider_id,
    hosted_model_id: model.model_id,
    default_model_family: model.model_id,
    label: model.label || model.model_id,
    description: provider.label || provider.provider_id,
    input_modalities: model.input_modalities || [],
    output_modalities: model.output_modalities || [],
  }));
}

function modelSupportsPlainHostedChat(model: { output_modalities?: string[] | null }): boolean {
  const outputs = model.output_modalities || [];
  return !outputs.length || outputs.includes("text");
}

function hostedRuntimeOptionId(providerId: string, modelId: string): string {
  return `hosted:${providerId}:${encodeURIComponent(modelId)}`;
}

function providerIsActive(provider: ProviderItem): boolean {
  return provider.status === "active";
}

function providerIsSelectable(provider: ProviderItem): boolean {
  return providerIsActive(provider) && (provider.provider_role === "runtime_engine" || providerUsesPlainHostedRuntime(provider));
}

function dedupeProviders(providers: ProviderItem[]): ProviderItem[] {
  const seen = new Set<string>();
  return providers.filter((provider) => {
    if (!provider.provider_id || seen.has(provider.provider_id)) {
      return false;
    }
    seen.add(provider.provider_id);
    return true;
  });
}
