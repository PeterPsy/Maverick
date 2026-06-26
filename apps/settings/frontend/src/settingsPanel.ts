import type { OpenRouterProviderRouting, PlatformSettings, ProviderModelOption, RuntimeSessionItem } from './adminApi';
import {
  defaultReasoningForOption,
  hostedModelOptionsForSettings,
  modelOptionsForSettings,
  selectedHostedProviderDraft,
  selectedProviderDraft
} from './providerModelOptions';

const ACTIVE_RUNTIME_STATUSES = new Set(['created', 'running', 'stopping']);

type HostedRoutingDraft = {
  allowFallbacks: boolean;
  dataCollection: '' | 'allow' | 'deny';
  mode: 'auto' | 'prefer' | 'only' | 'ignore';
  providerId: string;
  quantization: string;
  requireParameters: boolean;
  sort: '' | 'price' | 'throughput' | 'latency';
};

type HostedProviderModelGroup = {
  providerId: string;
  providerLabel: string;
  providerStatus: string;
  models: ProviderModelOption[];
};

export type SettingsPanelState = {
  cleanupError: string;
  clearingAllRuntime: boolean;
  cleaningSessionIds: Set<string>;
  draftModelId: string;
  draftReasoningEffort: string;
  hostedDraftModelId: string;
  hostedProviderError: string;
  hostedProviderErrorModelId: string;
  hostedRoutingDraftsByModel: Record<string, HostedRoutingDraft>;
  isSavingHostedProvider: boolean;
  isSavingProvider: boolean;
  isSavingSpeechProvider: boolean;
  providerError: string;
  speechAudioModelId: string;
  speechConversationModelId: string;
  speechProviderError: string;
};

export type SettingsPanelActions = {
  onClearAllRuntimeSessions: () => void;
  onClearRuntimeSession: (sessionId: string) => void;
  onLogout: () => void;
  onHostedProviderRoutingChanged: (modelId: string, field: string, value: string | boolean) => void;
  onSaveHostedProviderSettings: (modelId?: string) => void;
  onProviderModelChanged: (modelId: string) => void;
  onProviderReasoningChanged: (reasoningEffort: string) => void;
  onSaveProviderSettings: () => void;
  onSaveSpeechProviderSettings: () => void;
  onSpeechAudioModelChanged: (modelId: string) => void;
  onSpeechConversationModelChanged: (modelId: string) => void;
};

export function createSettingsPanelState(): SettingsPanelState {
  return {
    cleanupError: '',
    clearingAllRuntime: false,
    cleaningSessionIds: new Set(),
    draftModelId: '',
    draftReasoningEffort: '',
    hostedDraftModelId: '',
    hostedProviderError: '',
    hostedProviderErrorModelId: '',
    hostedRoutingDraftsByModel: {},
    isSavingHostedProvider: false,
    isSavingProvider: false,
    isSavingSpeechProvider: false,
    providerError: '',
    speechAudioModelId: '',
    speechConversationModelId: '',
    speechProviderError: ''
  };
}

export function syncSettingsPanelDraft(state: SettingsPanelState, settings: PlatformSettings | null) {
  const { modelId, reasoningEffort } = selectedProviderDraft(settings);
  const { modelId: hostedModelId } = selectedHostedProviderDraft(settings);
  const speechDraft = selectedSpeechProviderDraft(settings);
  const hostedModelIds = new Set(hostedModelOptionsForSettings(settings).map((option) => option.model_id).filter(Boolean));
  if (hostedModelId) {
    hostedModelIds.add(hostedModelId);
  }
  state.draftModelId = modelId;
  state.draftReasoningEffort = reasoningEffort;
  state.hostedDraftModelId = hostedModelId;
  state.speechAudioModelId = speechDraft.audioModelId;
  state.speechConversationModelId = speechDraft.conversationModelId;
  state.hostedRoutingDraftsByModel = Object.fromEntries(
    Array.from(hostedModelIds).map((modelId) => [modelId, routingDraftFromRouting(openRouterRoutingForModel(settings, modelId))])
  );
}

export function updateDraftModel(state: SettingsPanelState, settings: PlatformSettings | null, modelId: string) {
  const option = modelOptionsForSettings(settings).find((item) => item.model_id === modelId) || null;
  state.draftModelId = modelId;
  state.draftReasoningEffort = defaultReasoningForOption(option);
  state.providerError = '';
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

export function settingsPanelHtml(settings: PlatformSettings | null, state: SettingsPanelState) {
  if (!settings) {
    return `<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;
  }

  const provider = settings.provider.active_provider;
  const hostedProvider = settings.provider.hosted_text?.active_provider || null;
  const speechStt = settings.provider.speech_stt || null;
  const runtimeSessions = scopedRuntimeSessions(settings);
  const activeRuntimeSessions = runtimeSessions.filter((session) => ACTIVE_RUNTIME_STATUSES.has(session.status));
  const cleanupAllowed = settings.runtime.cleanup_allowed ?? false;
  const cleanupScope = settings.runtime.cleanup_scope || 'none';
  const modelOptions = modelOptionsForSettings(settings);
  const hostedModelOptions = hostedModelOptionsForSettings(settings);
  const hostedTextModelOptions = hostedModelOptions.filter(modelSupportsTextOutput);
  const hostedSpeechModelOptions = hostedModelOptions.filter(modelSupportsSpeechOutput);
  const selectedModel = selectedProviderDraft(settings).modelId;
  const selectedReasoning = selectedProviderDraft(settings).reasoningEffort;
  const selectedOption = modelOptions.find((option) => option.model_id === state.draftModelId) || modelOptions[0] || null;
  const reasoningOptions = selectedOption?.supported_reasoning_efforts || [];
  const openHostedModel = openHostedModelId(settings, state);
  const canSaveProvider = Boolean(
    provider &&
      state.draftModelId &&
      !state.isSavingProvider &&
      (state.draftModelId !== selectedModel || state.draftReasoningEffort !== selectedReasoning)
  );

  return `${userSettingsCardHtml(settings)}
    ${agenticModelSettingsCardHtml(
      provider,
      modelOptions,
      reasoningOptions,
      canSaveProvider,
      activeRuntimeSessions.length,
      runtimeSessions.length,
      false,
      state
    )}
    ${hostedTextModelSettingsCardHtml(
      openHostedModel,
      hostedTextModelOptions,
      hostedProvider,
      settings,
      state
    )}
    ${speechModelSettingsCardHtml(
      hostedSpeechModelOptions,
      openHostedModel,
      hostedProvider,
      speechStt,
      settings,
      state
    )}
    ${runtimeSessionsHtml(runtimeSessions, cleanupAllowed, cleanupScope, state)}`;
}

function userSettingsCardHtml(settings: PlatformSettings) {
  return `<section class="settings-card settings-platform settings-user-settings-card">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Account</p>
        <h2>User settings</h2>
      </div>
    </div>
    <article class="settings-platform-tile settings-platform-user">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">manage_accounts</span>
      <div>
        <p class="settings-kicker">Current user</p>
        <h3>${escapeHtml(settings.user.display_name || settings.user.username || 'Unavailable')}</h3>
        <p>${escapeHtml(settings.user.platform_role || 'member')} · ${escapeHtml(settings.workspace.name || settings.workspace.workspace_id)}</p>
        <button type="button" class="settings-secondary settings-platform-logout" id="settings-logout">
          <span class="material-symbols-rounded" aria-hidden="true">logout</span>
          Logout
        </button>
      </div>
    </article>
  </section>`;
}

function hostedTextModelSettingsCardHtml(
  openHostedModel: string,
  hostedModelOptions: ProviderModelOption[],
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  return `<section class="settings-card settings-platform settings-hosted-text-model-settings-card">
    ${modelSettingsHeadingHtml('route', 'Hosted text model settings')}
    ${hostedProviderSettingsListHtml({
      modelOptions: hostedModelOptions,
      openHostedModel,
      hostedProvider,
      settings,
      state,
      emptyMessage: 'No hosted text models are available from the active hosted providers.',
      inactiveMessage: 'Activate a hosted text provider before selecting a fast model.'
    })}
  </section>`;
}

function modelSettingsHeadingHtml(icon: string, title: string) {
  return `<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(icon)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${escapeHtml(title)}</h2>
      </div>
    </div>`;
}

function agenticModelSettingsCardHtml(
  provider: PlatformSettings['provider']['active_provider'] | null,
  modelOptions: ProviderModelOption[],
  reasoningOptions: ProviderModelOption['supported_reasoning_efforts'],
  canSaveProvider: boolean,
  activeRuntimeSessionCount: number,
  runtimeSessionCount: number,
  isOpen: boolean,
  state: SettingsPanelState
) {
  return `<section class="settings-card settings-platform settings-agentic-model-settings-card">
    ${modelSettingsHeadingHtml('memory', 'Agentic model settings')}
    <div class="settings-platform-provider-forms">
      ${providerSettingsFormHtml(provider, modelOptions, reasoningOptions, canSaveProvider, activeRuntimeSessionCount, runtimeSessionCount, isOpen, state)}
    </div>
  </section>`;
}

function speechModelSettingsCardHtml(
  hostedSpeechModelOptions: ProviderModelOption[],
  openHostedModel: string,
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  speechStt: PlatformSettings['provider']['speech_stt'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  return `<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${modelSettingsHeadingHtml('record_voice_over', 'Speech model settings')}
    <div class="settings-platform-provider-forms">
      ${hostedProviderSettingsListHtml({
        modelOptions: hostedSpeechModelOptions,
        openHostedModel,
        hostedProvider,
        settings,
        state,
        emptyMessage: 'No hosted speech models are available from the active hosted providers.',
        inactiveMessage: 'Activate the hosted provider before saving speech model routing.'
      })}
      ${speechSttSettingsListHtml(speechStt, state)}
    </div>
  </section>`;
}

export function bindSettingsPanelEvents(actions: SettingsPanelActions) {
  document.getElementById('settings-provider-model')?.addEventListener('change', (event) => {
    actions.onProviderModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('settings-provider-reasoning')?.addEventListener('change', (event) => {
    actions.onProviderReasoningChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('settings-speech-audio-model')?.addEventListener('change', (event) => {
    actions.onSpeechAudioModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('settings-speech-conversation-model')?.addEventListener('change', (event) => {
    actions.onSpeechConversationModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.querySelectorAll<HTMLButtonElement>('[data-speech-save]').forEach((button) => {
    button.addEventListener('click', () => {
      actions.onSaveSpeechProviderSettings();
    });
  });
  document.getElementById('settings-speech-save')?.addEventListener('click', () => {
    actions.onSaveSpeechProviderSettings();
  });
  document.querySelectorAll<HTMLDetailsElement>('[data-settings-model-accordion]').forEach((details) => {
    details.addEventListener('toggle', () => {
      if (!details.open) return;
      document.querySelectorAll<HTMLDetailsElement>('[data-settings-model-accordion]').forEach((otherDetails) => {
        if (otherDetails !== details) {
          otherDetails.open = false;
        }
      });
    });
  });
  document.querySelectorAll<HTMLElement>('[data-openrouter-routing]').forEach((element) => {
    element.addEventListener('change', (event) => {
      const target = event.currentTarget as HTMLInputElement | HTMLSelectElement;
      const modelId =
        target.dataset.hostedModelId ||
        target.closest<HTMLElement>('[data-hosted-model-accordion]')?.dataset.hostedModelAccordion ||
        '';
      actions.onHostedProviderRoutingChanged(
        modelId,
        target.dataset.openrouterRouting || '',
        target instanceof HTMLInputElement && target.type === 'checkbox' ? target.checked : target.value
      );
    });
  });
  document.getElementById('settings-save-provider')?.addEventListener('click', actions.onSaveProviderSettings);
  document.querySelectorAll<HTMLButtonElement>('[data-hosted-provider-save]').forEach((button) => {
    button.addEventListener('click', () => actions.onSaveHostedProviderSettings(button.dataset.hostedProviderSave || ''));
  });
  document.getElementById('settings-logout')?.addEventListener('click', actions.onLogout);
  document.getElementById('settings-clear-all-runtime')?.addEventListener('click', actions.onClearAllRuntimeSessions);
  document.querySelectorAll<HTMLButtonElement>('[data-runtime-clear]').forEach((button) => {
    button.addEventListener('click', () => actions.onClearRuntimeSession(button.dataset.runtimeClear || ''));
  });
}

function providerSettingsFormHtml(
  provider: PlatformSettings['provider']['active_provider'] | null,
  modelOptions: ProviderModelOption[],
  reasoningOptions: ProviderModelOption['supported_reasoning_efforts'],
  canSaveProvider: boolean,
  activeRuntimeSessionCount: number,
  runtimeSessionCount: number,
  isOpen: boolean,
  state: SettingsPanelState
) {
  return `<details class="settings-model-accordion settings-agentic-provider-accordion" data-settings-model-accordion="agentic-provider" data-agentic-provider-accordion ${isOpen ? 'open' : ''}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Agentic provider</span>
        </span>
        <strong>${escapeHtml(provider?.label || 'Provider not loaded')}</strong>
        <small>${escapeHtml(state.draftModelId || 'model')} · ${escapeHtml(state.draftReasoningEffort || 'reasoning')} · Codex tools/filesystem/MCP · ${activeRuntimeSessionCount} active / ${runtimeSessionCount} in scope</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-agentic-provider-content">
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!modelOptions.length || state.isSavingProvider ? 'disabled' : ''}>
        ${modelOptions.map((option) => `<option value="${escapeAttr(option.model_id)}" ${option.model_id === state.draftModelId ? 'selected' : ''}>${escapeHtml(option.label || option.model_id)}</option>`).join('')}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!reasoningOptions.length || state.isSavingProvider ? 'disabled' : ''}>
        ${reasoningOptions.map((option) => `<option value="${escapeAttr(option.effort)}" ${option.effort === state.draftReasoningEffort ? 'selected' : ''}>${escapeHtml(option.label || option.effort)}</option>`).join('')}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${canSaveProvider ? '' : 'disabled'}>
      <span class="material-symbols-rounded" aria-hidden="true">${state.isSavingProvider ? 'sync' : 'save'}</span>
      ${state.isSavingProvider ? 'Saving' : 'Save model'}
    </button>
    ${state.providerError ? `<p class="settings-platform-error">${escapeHtml(state.providerError)}</p>` : ''}
    </div>
  </details>`;
}

function hostedProviderSettingsListHtml({
  modelOptions,
  openHostedModel,
  hostedProvider,
  settings,
  state,
  emptyMessage,
  inactiveMessage
}: {
  modelOptions: ProviderModelOption[];
  openHostedModel: string;
  hostedProvider: PlatformSettings['provider']['active_provider'] | null;
  settings: PlatformSettings;
  state: SettingsPanelState;
  emptyMessage: string;
  inactiveMessage: string;
}) {
  const hasHostedProvider = Boolean(hostedProvider);
  const providerGroups = hostedProviderModelGroups(modelOptions, hostedProvider);
  return `<div class="settings-hosted-models">
    ${
      modelOptions.length
        ? providerGroups.map((group) => hostedProviderModelGroupHtml(group, openHostedModel, hostedProvider, settings, state)).join('')
        : `<p class="settings-card-copy settings-platform-note">${escapeHtml(emptyMessage)}</p>`
    }
    ${!hasHostedProvider ? `<p class="settings-card-copy settings-platform-note">${escapeHtml(inactiveMessage)}</p>` : ''}
  </div>`;
}

function hostedProviderModelGroupHtml(
  group: HostedProviderModelGroup,
  openHostedModel: string,
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  const statusPill = group.providerStatus === 'active' ? 'Active provider' : 'Inactive provider';
  return `<section class="settings-hosted-provider-group" data-hosted-provider-group="${escapeAttr(group.providerId)}">
    <div class="settings-hosted-provider-heading">
      <span>
        <strong>${escapeHtml(group.providerLabel)}</strong>
        <small>${group.models.length} ${group.models.length === 1 ? 'model' : 'models'}</small>
      </span>
      <span class="settings-pill">${escapeHtml(statusPill)}</span>
    </div>
    ${group.models.map((option) => hostedProviderModelAccordionHtml(option, openHostedModel, hostedProvider, settings, state)).join('')}
  </section>`;
}

function hostedProviderModelAccordionHtml(
  option: ProviderModelOption,
  openHostedModel: string,
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  const modelId = option.model_id;
  const draft = hostedRoutingDraftForModel(state, settings, modelId);
  const upstreamOptions = option.upstream_provider_options || [];
  const hasOpenRouterRouting = upstreamOptions.length > 0;
  const quantizations = Array.from(new Set(upstreamOptions.map((option) => option.quantization || '').filter(Boolean)));
  const modelProviderId = hostedProviderIdForModel(option, hostedProvider);
  const modelProviderStatus = hostedProviderStatusForModel(option, hostedProvider);
  const hasHostedProvider = Boolean(modelProviderId);
  const isSavingThisModel = state.isSavingHostedProvider && state.hostedDraftModelId === modelId;
  const selectedHostedProviderId = settings.provider.hosted_text?.selection?.provider_id || hostedProvider?.provider_id || '';
  const selectedHostedModelId =
    modelProviderId === selectedHostedProviderId
      ? settings.provider.hosted_text?.model_settings?.selected_model_id || hostedProvider?.default_model_family || ''
      : '';
  const canSaveProvider = Boolean(
    hasHostedProvider &&
      modelProviderStatus === 'active' &&
      modelId &&
      !state.isSavingHostedProvider &&
      (modelProviderId !== selectedHostedProviderId || modelId !== selectedHostedModelId || hostedRoutingChanged(state, settings, modelId))
  );
  const isTextOutputModel = modelSupportsTextOutput(option);
  const modelKindLabel = isTextOutputModel ? 'Hosted chat / fast model' : 'Hosted speech model';
  const modelRuntimeLabel = isTextOutputModel
    ? 'plain hosted chat capable · runtime engine remains Codex'
    : 'speech synthesis metadata · not used by plain hosted chat';
  const modelIcon = isTextOutputModel ? 'bolt' : 'record_voice_over';
  const isOpen = modelId === openHostedModel;
  const providerLabel = hostedProviderLabelForModel(option, hostedProvider);
  return `<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${escapeAttr(modelId)}" data-hosted-model-accordion="${escapeAttr(modelId)}" ${isOpen ? 'open' : ''}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${modelIcon}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${modelKindLabel}</span>
        </span>
        <strong>${escapeHtml(option.label || modelId)} - ${escapeHtml(providerLabel)}</strong>
        <small>${escapeHtml(modelId || 'model not selected')} · ${modelRuntimeLabel}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Model</span>
        <code class="settings-model-code">${escapeHtml(modelId || 'model not selected')}</code>
      </div>
    ${
      hasOpenRouterRouting
        ? `
    <label class="settings-platform-field">
      <span>OpenRouter upstream</span>
      <select data-openrouter-routing="mode" data-hosted-model-id="${escapeAttr(modelId)}" ${!hasHostedProvider || !upstreamOptions.length || state.isSavingHostedProvider ? 'disabled' : ''}>
        ${[
          ['auto', 'Auto'],
          ['prefer', 'Prefer selected'],
          ['only', 'Only selected'],
          ['ignore', 'Ignore selected']
        ].map(([value, label]) => `<option value="${escapeAttr(value)}" ${value === draft.mode ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${escapeAttr(modelId)}" ${!hasHostedProvider || !upstreamOptions.length || draft.mode === 'auto' || state.isSavingHostedProvider ? 'disabled' : ''}>
        <option value="">Select provider</option>
        ${upstreamOptions.map((option) => `<option value="${escapeAttr(String(option.provider_id || option.tag || ''))}" ${(option.provider_id || option.tag) === draft.providerId ? 'selected' : ''}>${escapeHtml(option.label || option.provider_id || option.tag || 'Provider')}</option>`).join('')}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${escapeAttr(modelId)}" ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}>
        ${[
          ['', 'OpenRouter default'],
          ['price', 'Price'],
          ['throughput', 'Throughput'],
          ['latency', 'Latency']
        ].map(([value, label]) => `<option value="${escapeAttr(value)}" ${value === draft.sort ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${escapeAttr(modelId)}" ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}>
        ${[
          ['', 'OpenRouter default'],
          ['allow', 'Allow'],
          ['deny', 'Deny']
        ].map(([value, label]) => `<option value="${escapeAttr(value)}" ${value === draft.dataCollection ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${escapeAttr(modelId)}" ${!hasHostedProvider || !quantizations.length || state.isSavingHostedProvider ? 'disabled' : ''}>
        <option value="">Any</option>
        ${quantizations.map((value) => `<option value="${escapeAttr(value)}" ${value === draft.quantization ? 'selected' : ''}>${escapeHtml(value)}</option>`).join('')}
      </select>
    </label>
    <div class="settings-platform-checks">
      <label><input type="checkbox" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${escapeAttr(modelId)}" ${draft.allowFallbacks ? 'checked' : ''} ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}> Allow OpenRouter fallback</label>
      <label><input type="checkbox" data-openrouter-routing="require_parameters" data-hosted-model-id="${escapeAttr(modelId)}" ${draft.requireParameters ? 'checked' : ''} ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}> Require supported parameters</label>
    </div>
    `
        : ''
    }
    <button type="button" data-hosted-provider-save="${escapeAttr(modelId)}" ${canSaveProvider ? '' : 'disabled'}>
      <span class="material-symbols-rounded" aria-hidden="true">${isSavingThisModel ? 'sync' : 'save'}</span>
      ${isSavingThisModel ? 'Saving' : 'Save hosted model'}
    </button>
    ${state.hostedProviderError && state.hostedProviderErrorModelId === modelId ? `<p class="settings-platform-error">${escapeHtml(state.hostedProviderError)}</p>` : ''}
    </div>
  </details>`;
}

function hostedProviderModelGroups(
  modelOptions: ProviderModelOption[],
  fallbackProvider: PlatformSettings['provider']['active_provider'] | null
): HostedProviderModelGroup[] {
  const groupsByProvider = new Map<string, HostedProviderModelGroup>();
  for (const option of modelOptions) {
    const providerId = hostedProviderIdForModel(option, fallbackProvider) || 'hosted-provider';
    const existing = groupsByProvider.get(providerId);
    if (existing) {
      existing.models.push(option);
      continue;
    }
    groupsByProvider.set(providerId, {
      providerId,
      providerLabel: hostedProviderLabelForModel(option, fallbackProvider),
      providerStatus: hostedProviderStatusForModel(option, fallbackProvider),
      models: [option]
    });
  }
  return Array.from(groupsByProvider.values()).sort((left, right) => {
    if (left.providerStatus === 'active' && right.providerStatus !== 'active') {
      return -1;
    }
    if (right.providerStatus === 'active' && left.providerStatus !== 'active') {
      return 1;
    }
    return left.providerLabel.localeCompare(right.providerLabel);
  });
}

function modelSupportsTextOutput(option: ProviderModelOption): boolean {
  const outputs = option.output_modalities || [];
  return !outputs.length || outputs.includes('text');
}

function modelSupportsSpeechOutput(option: ProviderModelOption): boolean {
  return (option.output_modalities || []).includes('speech');
}

function hostedProviderIdForModel(
  option: ProviderModelOption,
  fallbackProvider: PlatformSettings['provider']['active_provider'] | null
): string {
  const value = option.metadata?.hosted_provider_id;
  return typeof value === 'string' && value ? value : fallbackProvider?.provider_id || '';
}

function hostedProviderLabelForModel(
  option: ProviderModelOption,
  fallbackProvider: PlatformSettings['provider']['active_provider'] | null
): string {
  const value = option.metadata?.hosted_provider_label;
  return typeof value === 'string' && value ? value : fallbackProvider?.label || fallbackProvider?.provider_id || 'Hosted provider';
}

function hostedProviderStatusForModel(
  option: ProviderModelOption,
  fallbackProvider: PlatformSettings['provider']['active_provider'] | null
): string {
  const value = option.metadata?.hosted_provider_status;
  return typeof value === 'string' && value ? value : fallbackProvider?.status || '';
}

function speechSttSettingsListHtml(status: PlatformSettings['provider']['speech_stt'] | null, state: SettingsPanelState) {
  const provider = status?.active_provider || status?.available_providers?.find((item) => item.provider_id === 'deepgram') || null;
  const audioOptions = speechModelOptions(status, provider, 'prerecorded_transcription');
  const conversationOptions = speechModelOptions(status, provider, 'conversational_streaming');
  const selectedAudioModelId = status?.model_settings?.audio_transcription_model_id || audioOptions[0]?.model_id || 'nova-3';
  const selectedConversationModelId = status?.model_settings?.conversation_model_id || conversationOptions[0]?.model_id || 'flux-general-multi';
  const audioDraft = state.speechAudioModelId || selectedAudioModelId;
  const conversationDraft = state.speechConversationModelId || selectedConversationModelId;
  const audioOption = audioOptions.find((option) => option.model_id === audioDraft) || audioOptions[0] || null;
  const conversationOption = conversationOptions.find((option) => option.model_id === conversationDraft) || conversationOptions[0] || null;
  const audioEndpoint = speechModelEndpoint(audioOption, status?.model_settings?.endpoints?.audio_transcription || `https://api.deepgram.com/v1/listen?model=${audioDraft || 'nova-3'}`);
  const conversationEndpoint = speechModelEndpoint(conversationOption, status?.model_settings?.endpoints?.conversation || `wss://api.deepgram.com/v2/listen?model=${conversationDraft || 'flux-general-multi'}`);
  const active = Boolean(status?.active_provider && status?.credential_binding);
  const canSave = Boolean(
    active &&
      audioDraft &&
      conversationDraft &&
      !state.isSavingSpeechProvider &&
      (audioDraft !== selectedAudioModelId || conversationDraft !== selectedConversationModelId)
  );
  const providerLabel = provider?.label || provider?.provider_id || 'Deepgram';
  const providerId = provider?.provider_id || 'deepgram';
  const providerStatus = active ? 'Active provider' : 'Inactive provider';
  return `<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${escapeAttr(providerId)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${escapeHtml(providerLabel)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${escapeHtml(providerStatus)}</span>
      </div>
      ${speechModelSelectHtml({
        id: 'settings-speech-audio-model',
        label: 'Audio transcription model',
        icon: 'hearing',
        value: audioDraft,
        options: audioOptions,
        endpoint: audioEndpoint,
        description: audioOption?.description || 'Deepgram model for prerecorded audio, files, and one-shot microphone transcription.',
        disabled: !active || state.isSavingSpeechProvider,
        canSave,
        isSaving: state.isSavingSpeechProvider
      })}
      ${speechModelSelectHtml({
        id: 'settings-speech-conversation-model',
        label: 'Conversation model',
        icon: 'forum',
        value: conversationDraft,
        options: conversationOptions,
        endpoint: conversationEndpoint,
        description: conversationOption?.description || 'Deepgram Flux model for realtime voice conversation and turn detection.',
        disabled: !active || state.isSavingSpeechProvider,
        canSave,
        isSaving: state.isSavingSpeechProvider
      })}
    </section>
    ${state.speechProviderError ? `<p class="settings-platform-error">${escapeHtml(state.speechProviderError)}</p>` : ''}
    ${active ? '' : '<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`;
}

function speechModelSelectHtml({
  id,
  label,
  icon,
  value,
  options,
  endpoint,
  description,
  disabled,
  canSave,
  isSaving
}: {
  id: string;
  label: string;
  icon: string;
  value: string;
  options: ProviderModelOption[];
  endpoint: string;
  description: string;
  disabled: boolean;
  canSave: boolean;
  isSaving: boolean;
}) {
  if (!options.length) {
    return `<p class="settings-card-copy settings-platform-note">No ${escapeHtml(label.toLowerCase())} options are available.</p>`;
  }
  return `<details class="settings-model-accordion settings-speech-model-accordion">
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(icon)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${escapeHtml(label)}</span>
        </span>
        <strong>${escapeHtml(options.find((option) => option.model_id === value)?.label || value)}</strong>
        <small>${escapeHtml(value)} · ${escapeHtml(endpoint)}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${escapeHtml(label)}</span>
        <select id="${escapeAttr(id)}" ${disabled ? 'disabled' : ''}>
          ${options.map((option) => `<option value="${escapeAttr(option.model_id)}" ${option.model_id === value ? 'selected' : ''}>${escapeHtml(option.label || option.model_id)}</option>`).join('')}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${escapeHtml(endpoint)}</code>
      </div>
      <p class="settings-card-copy">${escapeHtml(description)}</p>
      <button type="button" data-speech-save="${escapeAttr(id)}" ${canSave ? '' : 'disabled'}>
        <span class="material-symbols-rounded" aria-hidden="true">${isSaving ? 'sync' : 'save'}</span>
        ${isSaving ? 'Saving' : 'Save speech model'}
      </button>
    </div>
  </details>`;
}

function speechModelOptions(
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

function speechModelEndpoint(option: ProviderModelOption | null, fallback: string) {
  const endpoint = option?.metadata?.endpoint;
  return typeof endpoint === 'string' && endpoint ? endpoint : fallback;
}

function runtimeSessionsHtml(
  sessions: RuntimeSessionItem[],
  cleanupAllowed: boolean,
  cleanupScope: string,
  state: SettingsPanelState
) {
  const scopeLabel =
    cleanupScope === 'server'
      ? 'Scope: full server'
      : cleanupScope === 'workspace'
        ? 'Scope: active workspace'
        : 'Runtime cleanup is not allowed in this workspace';
  return `<section class="settings-card settings-platform settings-runtime-settings-card">
    <details class="settings-platform-runtime" open>
    <summary class="settings-heading settings-collapsible-heading">
      <div>
        <p class="settings-kicker">Runtime</p>
        <h2>Agent sessions</h2>
      </div>
    </summary>
    <div class="settings-platform-runtime-toolbar">
      <span class="settings-card-copy">${scopeLabel}</span>
      <span class="settings-platform-runtime-actions">
        <span class="settings-pill">${sessions.length}</span>
        <button type="button" class="settings-secondary" id="settings-clear-all-runtime" ${!cleanupAllowed || !sessions.length || state.clearingAllRuntime ? 'disabled' : ''}>
          <span class="material-symbols-rounded" aria-hidden="true">${state.clearingAllRuntime ? 'sync' : 'cleaning_services'}</span>
          ${state.clearingAllRuntime ? 'Cleaning' : 'Clean all'}
        </button>
      </span>
    </div>
    ${!cleanupAllowed ? '<p class="settings-platform-error">Only authorized admins can clean runtime sessions in this scope.</p>' : ''}
    <div class="settings-platform-runtime-list">
      ${sessions.length ? sessions.map((session) => runtimeSessionRowHtml(session, cleanupAllowed, state)).join('') : '<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${state.cleanupError ? `<p class="settings-platform-error">${escapeHtml(state.cleanupError)}</p>` : ''}
  </details>
  </section>`;
}

function runtimeSessionRowHtml(session: RuntimeSessionItem, cleanupAllowed: boolean, state: SettingsPanelState) {
  const isCleaning = state.cleaningSessionIds.has(session.session_id);
  return `<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${escapeHtml(session.agent_id || session.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${escapeAttr(session.session_id)}" aria-label="Clean runtime session ${escapeAttr(session.agent_id || session.session_id)}" ${!cleanupAllowed || state.clearingAllRuntime || isCleaning ? 'disabled' : ''}>
          <span class="material-symbols-rounded" aria-hidden="true">${isCleaning ? 'sync' : 'delete_sweep'}</span>
          <span class="settings-platform-runtime-clear-label">${isCleaning ? 'Cleaning' : 'Clean'}</span>
        </button>
      </span>
      <small>${escapeHtml(session.workspace_name || session.workspace_id)} · ${escapeHtml(session.effective_mode)} · ${escapeHtml(session.status)}</small>
      <code>${escapeHtml(session.session_id)}</code>
    </span>
  </div>`;
}

function scopedRuntimeSessions(settings: PlatformSettings) {
  return settings.runtime.all_sessions || settings.runtime.sessions || [];
}

function openRouterRoutingForModel(settings: PlatformSettings | null, modelId: string): OpenRouterProviderRouting {
  const routing = settings?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[modelId];
  return {
    mode: routing?.mode || 'auto',
    provider_id: routing?.provider_id || '',
    allow_fallbacks: routing?.allow_fallbacks !== false,
    require_parameters: routing?.require_parameters === true,
    sort: routing?.sort || '',
    data_collection: routing?.data_collection || '',
    quantizations: routing?.quantizations || []
  };
}

function hostedRoutingChanged(state: SettingsPanelState, settings: PlatformSettings, modelId: string): boolean {
  const saved = openRouterRoutingForModel(settings, modelId);
  const draft = hostedProviderRoutingDraft(state, modelId);
  return (
    saved.mode !== draft.mode ||
    (saved.provider_id || '') !== (draft.provider_id || '') ||
    (saved.allow_fallbacks !== false) !== (draft.allow_fallbacks !== false) ||
    (saved.require_parameters === true) !== (draft.require_parameters === true) ||
    (saved.sort || '') !== (draft.sort || '') ||
    (saved.data_collection || '') !== (draft.data_collection || '') ||
    (saved.quantizations?.[0] || '') !== (draft.quantizations?.[0] || '')
  );
}

function openHostedModelId(settings: PlatformSettings, state: SettingsPanelState): string {
  if (state.hostedProviderErrorModelId) {
    return state.hostedProviderErrorModelId;
  }
  if (!state.hostedDraftModelId || !hostedRoutingChanged(state, settings, state.hostedDraftModelId)) {
    return '';
  }
  return state.hostedDraftModelId;
}

function hostedRoutingDraftForModel(state: SettingsPanelState, settings: PlatformSettings | null, modelId: string): HostedRoutingDraft {
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
    sort: routing.sort || ''
  };
}

function defaultHostedRoutingDraft(): HostedRoutingDraft {
  return routingDraftFromRouting({
    mode: 'auto',
    allow_fallbacks: true,
    require_parameters: false,
    sort: '',
    data_collection: '',
    quantizations: []
  });
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => {
    if (character === '&') return '&amp;';
    if (character === '<') return '&lt;';
    if (character === '>') return '&gt;';
    if (character === '"') return '&quot;';
    return '&#39;';
  });
}

function escapeAttr(value: string) {
  return escapeHtml(value);
}
