import type { ProviderItem, ProviderPayload, HostedTextProviderStatus } from "../api/client";
import type { AgentRuntimeConfig } from "../hooks/useMessageSubmission";

export function providerItemsFromPayload(payload: ProviderPayload): ProviderItem[] {
  const options: ProviderItem[] = [];
  if (payload.active_provider && providerIsActive(payload.active_provider)) {
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
        label: `${selectedModelId || "Hosted model"} - ${provider.label || provider.provider_id}`,
      },
    ];
  }
  return sortedModels.map((model) => ({
    ...provider,
    provider_id: hostedRuntimeOptionId(provider.provider_id, model.model_id),
    hosted_provider_id: provider.provider_id,
    hosted_model_id: model.model_id,
    default_model_family: model.model_id,
    label: `${model.label || model.model_id} - ${provider.label || provider.provider_id}`,
    description: model.description || provider.description,
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
