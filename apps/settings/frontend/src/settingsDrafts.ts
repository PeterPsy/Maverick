import { createSpeechSynthesisState } from './speechSynthesisSettings';
import { createComputerUseDraft, syncComputerUseDraft, type ComputerUseDraft } from './computerUseSettings';
import type { OpenRouterProviderRouting, PlatformSettings, ProviderSubscriptionUsage, UsageTimeSeriesPayload } from './adminApi';
import { hostedModelOptionsForSettings, selectedHostedProviderDraft } from './providerModelOptions';
import { defaultUsageHistoryFilters, type UsageHistoryFilters } from './usageHistoryFilters';

export type HostedRoutingDraft = {
  allowFallbacks: boolean;
  dataCollection: '' | 'allow' | 'deny';
  mode: 'auto' | 'prefer' | 'only' | 'ignore';
  providerId: string;
  quantization: string;
  requireParameters: boolean;
  sort: '' | 'price' | 'throughput' | 'latency';
  zdr: boolean;
};

export type SettingsPanelState = {
  computerUse: ComputerUseDraft;
  savedDrafts: { workspaceId: string; hostedModelId: string; audioModelId: string; conversationModelId: string; routing: Record<string, HostedRoutingDraft> } | null;
  speechSynthesis: import('./speechSynthesisSettings').SpeechSynthesisState;
  activatingNativeProviders: Set<string>;
  nativeProviderErrors: Record<string, string>;
  agenticBindingErrors: Record<string, string>;
  cleanupError: string;
  clearingAllRuntime: boolean;
  cleaningSessionIds: Set<string>;
  hostedDraftModelId: string;
  hostedProviderError: string;
  hostedProviderErrorModelId: string;
  hostedRoutingDraftsByModel: Record<string, HostedRoutingDraft>;
  isSavingHostedProvider: boolean;
  isSavingSpeechProvider: boolean;
  isLoadingProviderUsage: boolean;
  isLoadingUsageHistory: boolean;
  savingAgenticBindings: Set<string>;
  providerUsageError: string;
  providerUsageItems: ProviderSubscriptionUsage[];
  usageHistory: UsageTimeSeriesPayload | null;
  usageHistoryFilters: UsageHistoryFilters;
  usageHistoryError: string;
  speechAudioModelId: string;
  speechConversationModelId: string;
  speechProviderError: string;
};

export function createSettingsPanelState(): SettingsPanelState {
  return {
    computerUse: createComputerUseDraft(),
    savedDrafts: null,
    speechSynthesis: createSpeechSynthesisState(),
    activatingNativeProviders: new Set(),
    nativeProviderErrors: {},
    agenticBindingErrors: {},
    cleanupError: '',
    clearingAllRuntime: false,
    cleaningSessionIds: new Set(),
    hostedDraftModelId: '',
    hostedProviderError: '',
    hostedProviderErrorModelId: '',
    hostedRoutingDraftsByModel: {},
    isSavingHostedProvider: false,
    isSavingSpeechProvider: false,
    isLoadingProviderUsage: false,
    isLoadingUsageHistory: false,
    savingAgenticBindings: new Set(),
    providerUsageError: '',
    providerUsageItems: [],
    usageHistory: null,
    usageHistoryFilters: defaultUsageHistoryFilters(),
    usageHistoryError: '',
    speechAudioModelId: '',
    speechConversationModelId: '',
    speechProviderError: ''
  };
}

export function syncSettingsPanelDraft(state: SettingsPanelState, settings: PlatformSettings | null,
  replace: { speech?: boolean; hostedModelId?: string } = {}) {
  if (settings?.computer_use) syncComputerUseDraft(state.computerUse, settings);
  const workspaceId = settings?.workspace.workspace_id || '';
  const previous = state.savedDrafts?.workspaceId === workspaceId ? state.savedDrafts : null;
  const { modelId: hostedModelId } = selectedHostedProviderDraft(settings);
  const speech = selectedSpeechProviderDraft(settings);
  const modelIds = new Set([...hostedModelOptionsForSettings(settings).map(option => option.model_id),
    hostedModelId, ...Object.keys(previous ? state.hostedRoutingDraftsByModel : {})].filter(Boolean));
  const routing = Object.fromEntries(Array.from(modelIds).map(modelId =>
    [modelId, routingDraftFromRouting(openRouterRoutingForModel(settings, modelId))]));
  if (!previous || state.hostedDraftModelId === previous.hostedModelId || replace.hostedModelId) state.hostedDraftModelId = hostedModelId;
  if (!previous || state.speechAudioModelId === previous.audioModelId || replace.speech) state.speechAudioModelId = speech.audioModelId;
  if (!previous || state.speechConversationModelId === previous.conversationModelId || replace.speech) state.speechConversationModelId = speech.conversationModelId;
  state.hostedRoutingDraftsByModel = Object.fromEntries(Array.from(modelIds).map(modelId => {
    const draft = state.hostedRoutingDraftsByModel[modelId];
    const dirty = previous && draft && JSON.stringify(draft) !== JSON.stringify(previous.routing[modelId]);
    return [modelId, dirty && replace.hostedModelId !== modelId ? draft : routing[modelId]];
  }));
  state.savedDrafts = { workspaceId, hostedModelId, audioModelId: speech.audioModelId,
    conversationModelId: speech.conversationModelId, routing: Object.fromEntries(Object.entries(routing).map(([id, draft]) => [id, { ...draft }])) };
}

export function updateHostedDraftModel(state: SettingsPanelState, settings: PlatformSettings | null, modelId: string) {
  state.hostedDraftModelId = modelId;
  ensureHostedRoutingDraft(state, settings, modelId);
  state.hostedProviderError = '';
  state.hostedProviderErrorModelId = '';
}

export function updateSpeechAudioModel(state: SettingsPanelState, modelId: string) {
  state.speechAudioModelId = modelId;
  state.speechProviderError = '';
}

export function updateSpeechConversationModel(state: SettingsPanelState, modelId: string) {
  state.speechConversationModelId = modelId;
  state.speechProviderError = '';
}

export function updateHostedProviderRoutingDraft(
  state: SettingsPanelState,
  settings: PlatformSettings | null,
  modelId: string,
  field: string,
  value: string | boolean
) {
  if (!modelId) {
    return;
  }
  const draft = ensureHostedRoutingDraft(state, settings, modelId);
  state.hostedDraftModelId = modelId;
  if (field === 'mode' && typeof value === 'string' && ['auto', 'prefer', 'only', 'ignore'].includes(value)) {
    draft.mode = value as HostedRoutingDraft['mode'];
  } else if (field === 'provider_id' && typeof value === 'string') {
    draft.providerId = value;
  } else if (field === 'allow_fallbacks' && typeof value === 'boolean') {
    draft.allowFallbacks = value;
  } else if (field === 'require_parameters' && typeof value === 'boolean') {
    draft.requireParameters = value;
  } else if (field === 'zdr' && typeof value === 'boolean') {
    draft.zdr = value;
  } else if (field === 'sort' && typeof value === 'string' && ['', 'price', 'throughput', 'latency'].includes(value)) {
    draft.sort = value as HostedRoutingDraft['sort'];
  } else if (field === 'data_collection' && typeof value === 'string' && ['', 'allow', 'deny'].includes(value)) {
    draft.dataCollection = value as HostedRoutingDraft['dataCollection'];
  } else if (field === 'quantization' && typeof value === 'string') {
    draft.quantization = value;
  }
  state.hostedProviderError = '';
  state.hostedProviderErrorModelId = '';
}

export function hostedProviderRoutingDraft(state: SettingsPanelState, modelId = state.hostedDraftModelId): OpenRouterProviderRouting {
  const draft = state.hostedRoutingDraftsByModel[modelId] || defaultHostedRoutingDraft();
  return {
    mode: draft.mode,
    provider_id: draft.providerId || undefined,
    allow_fallbacks: draft.allowFallbacks,
    require_parameters: draft.requireParameters,
    zdr: draft.zdr,
    sort: draft.sort,
    data_collection: draft.dataCollection,
    quantizations: draft.quantization ? [draft.quantization] : []
  };
}

function selectedSpeechProviderDraft(settings: PlatformSettings | null | undefined) {
  const status = settings?.provider.speech_stt || null;
  const provider = status?.active_provider || status?.available_providers?.find((item) => item.provider_id === 'deepgram') || null;
  const audioOptions = speechModelOptions(status, provider, 'prerecorded_transcription');
  const conversationOptions = speechModelOptions(status, provider, 'conversational_streaming');
  return {
    audioModelId:
      status?.model_settings?.audio_transcription_model_id ||
      audioOptions.find((option) => option.model_id === 'nova-3')?.model_id ||
      audioOptions[0]?.model_id ||
      'nova-3',
    conversationModelId:
      status?.model_settings?.conversation_model_id ||
      conversationOptions.find((option) => option.model_id === 'flux-general-multi')?.model_id ||
      conversationOptions[0]?.model_id ||
      'flux-general-multi'
  };
}

export function speechModelOptions(
  status: PlatformSettings['provider']['speech_stt'] | null,
  provider: PlatformSettings['provider']['active_provider'] | null,
  purpose: 'prerecorded_transcription' | 'conversational_streaming'
) {
  const settingsOptions =
    purpose === 'prerecorded_transcription'
      ? status?.model_settings?.available_audio_transcription_models
      : status?.model_settings?.available_conversation_models;
  if (settingsOptions?.length) {
    return settingsOptions;
  }
  const allOptions = status?.model_settings?.available_models?.length ? status.model_settings.available_models : provider?.model_options || [];
  return allOptions.filter((option) => option.metadata?.purpose === purpose);
}

function openRouterRoutingForModel(settings: PlatformSettings | null, modelId: string): OpenRouterProviderRouting {
  const routing = settings?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[modelId];
  return {
    mode: routing?.mode || 'auto',
    provider_id: routing?.provider_id || '',
    allow_fallbacks: routing?.allow_fallbacks !== false,
    require_parameters: routing?.require_parameters === true,
    zdr: routing?.zdr === true,
    sort: routing?.sort || '',
    data_collection: routing?.data_collection || '',
    quantizations: routing?.quantizations || []
  };
}

export function hostedRoutingChanged(state: SettingsPanelState, settings: PlatformSettings, modelId: string): boolean {
  const saved = openRouterRoutingForModel(settings, modelId);
  const draft = hostedProviderRoutingDraft(state, modelId);
  return (
    saved.mode !== draft.mode ||
    (saved.provider_id || '') !== (draft.provider_id || '') ||
    (saved.allow_fallbacks !== false) !== (draft.allow_fallbacks !== false) ||
    (saved.require_parameters === true) !== (draft.require_parameters === true) ||
    (saved.zdr === true) !== (draft.zdr === true) ||
    (saved.sort || '') !== (draft.sort || '') ||
    (saved.data_collection || '') !== (draft.data_collection || '') ||
    (saved.quantizations?.[0] || '') !== (draft.quantizations?.[0] || '')
  );
}

export function openHostedModelId(settings: PlatformSettings, state: SettingsPanelState): string {
  if (state.hostedProviderErrorModelId) {
    return state.hostedProviderErrorModelId;
  }
  if (!state.hostedDraftModelId || !hostedRoutingChanged(state, settings, state.hostedDraftModelId)) {
    return '';
  }
  return state.hostedDraftModelId;
}

export function hostedRoutingDraftForModel(state: SettingsPanelState, settings: PlatformSettings | null, modelId: string): HostedRoutingDraft {
  return state.hostedRoutingDraftsByModel[modelId] || routingDraftFromRouting(openRouterRoutingForModel(settings, modelId));
}

function ensureHostedRoutingDraft(state: SettingsPanelState, settings: PlatformSettings | null, modelId: string): HostedRoutingDraft {
  if (!state.hostedRoutingDraftsByModel[modelId]) {
    state.hostedRoutingDraftsByModel[modelId] = routingDraftFromRouting(openRouterRoutingForModel(settings, modelId));
  }
  return state.hostedRoutingDraftsByModel[modelId];
}

function routingDraftFromRouting(routing: OpenRouterProviderRouting): HostedRoutingDraft {
  return {
    allowFallbacks: routing.allow_fallbacks !== false,
    dataCollection: routing.data_collection || '',
    mode: routing.mode || 'auto',
    providerId: routing.provider_id || '',
    quantization: routing.quantizations?.[0] || '',
    requireParameters: routing.require_parameters === true,
    sort: routing.sort || '',
    zdr: routing.zdr === true
  };
}

function defaultHostedRoutingDraft(): HostedRoutingDraft {
  return routingDraftFromRouting({
    mode: 'auto',
    allow_fallbacks: true,
    require_parameters: false,
    zdr: false,
    sort: '',
    data_collection: '',
    quantizations: []
  });
}

