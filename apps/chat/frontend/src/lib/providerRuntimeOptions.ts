import type { ProviderItem, ProviderPayload, HostedTextProviderStatus } from "../api/client";
import type { AgentRuntimeConfig } from "../hooks/useMessageSubmission";

export function providerItemsFromPayload(payload: ProviderPayload): ProviderItem[] {
  const options: ProviderItem[] = [];
  if (payload.active_provider && providerIsActive(payload.active_provider)) {
    options.push(payload.active_provider);
  }

  const hostedProvider = payload.hosted_text?.active_provider || null;
  if (hostedProvider && providerIsActive(hostedProvider)) {
    options.push({
      ...hostedProvider,
      label: hostedProviderLabel(payload.hosted_text),
    });
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
  return {
    agent_id: "chat",
    agent_role_id: "",
    agent_type_id: "",
    runtime_mode: "plain_hosted_chat",
    routing_profile: "fast_model",
    skill_catalog_app_id: "",
    skill_ids: [],
    source_app_id: "chat",
    system_prompt: "",
    title: provider?.label || "Hosted chat",
  };
}

function hostedProviderLabel(status: HostedTextProviderStatus | null | undefined): string {
  const provider = status?.active_provider;
  if (!provider) {
    return "Hosted model";
  }
  const selectedModelId = status?.model_settings?.selected_model_id || provider.default_model_family || "";
  const model =
    status?.model_settings?.available_models?.find((option) => option.model_id === selectedModelId) ||
    provider.model_options?.find((option) => option.model_id === selectedModelId) ||
    null;
  return `${model?.label || selectedModelId || "Hosted model"} - ${provider.label || provider.provider_id}`;
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
