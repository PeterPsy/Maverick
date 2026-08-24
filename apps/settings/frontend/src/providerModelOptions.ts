import type { PlatformSettings, ProviderModelOption } from './adminApi';

export function selectedProviderDraft(settings: PlatformSettings | null) {
  const provider = settings?.provider.active_provider;
  const modelSettings = settings?.provider.model_settings;
  return selectedDraft(provider, modelSettings);
}

export function modelOptionsForSettings(settings: PlatformSettings | null) {
  const provider = settings?.provider.active_provider;
  const modelSettings = settings?.provider.model_settings;
  return modelOptionsForProvider(provider, modelSettings);
}

export function selectedHostedProviderDraft(settings: PlatformSettings | null) {
  const provider = settings?.provider.hosted_text?.active_provider || null;
  const modelSettings = settings?.provider.hosted_text?.model_settings || null;
  return selectedDraft(provider, modelSettings);
}

export function hostedModelOptionsForSettings(settings: PlatformSettings | null) {
  const status = settings?.provider.hosted_text || null;
  const activeProvider = status?.active_provider || null;
  const providers = status?.available_providers?.length
    ? status.available_providers
    : activeProvider
      ? [activeProvider]
      : [];
  return providers.flatMap((provider) => {
    const modelSettings = provider.provider_id === activeProvider?.provider_id ? status?.model_settings || null : null;
    return modelOptionsForProvider(provider, modelSettings).map((option) => ({
      ...option,
      metadata: {
        ...(option.metadata || {}),
        hosted_provider_id: provider.provider_id,
        hosted_provider_label: provider.label || provider.provider_id,
        hosted_provider_status: provider.status
      }
    }));
  });
}

function selectedDraft(
  provider: PlatformSettings['provider']['active_provider'] | null | undefined,
  modelSettings: PlatformSettings['provider']['model_settings'] | null | undefined
) {
  const selectedModel = modelSettings?.selected_model_id || provider?.default_model_family || '';
  return {
    modelId: selectedModel
  };
}

function modelOptionsForProvider(
  provider: PlatformSettings['provider']['active_provider'] | null | undefined,
  modelSettings: PlatformSettings['provider']['model_settings'] | null | undefined
) {
  const selectedModel = modelSettings?.selected_model_id || provider?.default_model_family || '';
  const rawOptions = usableModelOptions(modelSettings?.available_models).length
    ? usableModelOptions(modelSettings?.available_models)
    : usableModelOptions(provider?.model_options);
  return (rawOptions.length ? rawOptions : selectedModel ? [fallbackModelOption(selectedModel, modelSettings?.selected_reasoning_effort || '')] : []).map(withReasoningFallback);
}

export function defaultReasoningForOption(option: ProviderModelOption | null) {
  return option?.default_reasoning_effort || option?.supported_reasoning_efforts[0]?.effort || '';
}

function usableModelOptions(options: ProviderModelOption[] | null | undefined) {
  return (options || []).filter((option) => option.model_id);
}

function withReasoningFallback(option: ProviderModelOption): ProviderModelOption {
  if (option.supported_reasoning_efforts.length || !option.default_reasoning_effort) {
    return option;
  }
  return {
    ...option,
    supported_reasoning_efforts: [{
      effort: option.default_reasoning_effort,
      label: option.default_reasoning_effort,
      description: null
    }]
  };
}

function fallbackModelOption(modelId: string, reasoningEffort: string): ProviderModelOption {
  return {
    model_id: modelId,
    label: modelId,
    description: null,
    default_reasoning_effort: reasoningEffort || null,
    supported_reasoning_efforts: reasoningEffort ? [{ effort: reasoningEffort, label: reasoningEffort, description: null }] : []
  };
}
