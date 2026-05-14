import type { PlatformSettings, ProviderModelOption } from './adminApi';

export function selectedProviderDraft(settings: PlatformSettings | null) {
  const provider = settings?.provider.active_provider;
  const modelSettings = settings?.provider.model_settings;
  const selectedModel = modelSettings?.selected_model_id || provider?.default_model_family || '';
  const selectedOption = modelOptionsForSettings(settings).find((option) => option.model_id === selectedModel) || null;
  return {
    modelId: selectedModel,
    reasoningEffort: modelSettings?.selected_reasoning_effort || defaultReasoningForOption(selectedOption)
  };
}

export function modelOptionsForSettings(settings: PlatformSettings | null) {
  const provider = settings?.provider.active_provider;
  const modelSettings = settings?.provider.model_settings;
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
