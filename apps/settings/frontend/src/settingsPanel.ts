import type {
  AgenticAdminItem,
  AgenticAdminPayload,
  OpenRouterProviderRouting,
  PlatformSettings,
  ProviderModelOption,
  ProviderSubscriptionUsage,
  UsageTimeSeriesPayload,
  ProviderUsageLimit,
  ProviderUsageWindow,
  RuntimeSessionItem
} from './adminApi';
import {
  defaultReasoningForOption,
  hostedModelOptionsForSettings,
  modelOptionsForSettings,
  selectedHostedProviderDraft,
  selectedProviderDraft
} from './providerModelOptions';
import { bouncyToggleHtml } from './bouncyToggle';
import { defaultUsageHistoryFilters, type UsageHistoryFilters } from './usageHistoryFilters';

const ACTIVE_RUNTIME_STATUSES = new Set(['created', 'running', 'stopping', 'recovery_required']);

type HostedRoutingDraft = {
  allowFallbacks: boolean;
  dataCollection: '' | 'allow' | 'deny';
  mode: 'auto' | 'prefer' | 'only' | 'ignore';
  providerId: string;
  quantization: string;
  requireParameters: boolean;
  sort: '' | 'price' | 'throughput' | 'latency';
  zdr: boolean;
};

type HostedProviderModelGroup = {
  providerId: string;
  providerLabel: string;
  providerStatus: string;
  models: ProviderModelOption[];
};

export type SettingsPanelState = {
  agenticBindingErrors: Record<string, string>;
  cleanupError: string;
  clearingAllRuntime: boolean;
  cleaningSessionIds: Set<string>;
  draftModelId: string;
  hostedDraftModelId: string;
  hostedProviderError: string;
  hostedProviderErrorModelId: string;
  hostedRoutingDraftsByModel: Record<string, HostedRoutingDraft>;
  isSavingHostedProvider: boolean;
  isSavingProvider: boolean;
  isSavingSpeechProvider: boolean;
  isLoadingProviderUsage: boolean;
  isLoadingUsageHistory: boolean;
  savingAgenticBindings: Set<string>;
  providerError: string;
  providerUsageError: string;
  providerUsageItems: ProviderSubscriptionUsage[];
  hourlyUsage: UsageTimeSeriesPayload | null;
  dailyUsage: UsageTimeSeriesPayload | null;
  usageHistoryFilters: UsageHistoryFilters;
  usageHistoryError: string;
  speechAudioModelId: string;
  speechConversationModelId: string;
  speechProviderError: string;
};

export type SettingsPanelActions = {
  onClearAllRuntimeSessions: () => void;
  onClearRuntimeSession: (sessionId: string) => void;
  onLogout: () => void;
  onHostedProviderRoutingChanged: (modelId: string, field: string, value: string | boolean) => void;
  onSaveAgenticBinding: (
    definitionId: string,
    definitionRevision: string,
    options?: { enabled?: boolean }
  ) => void;
  onSaveHostedProviderSettings: (modelId?: string) => void;
  onProviderModelChanged: (modelId: string) => void;
  onRefreshProviderUsage: () => void;
  onSaveProviderSettings: () => void;
  onSaveSpeechProviderSettings: () => void;
  onSpeechAudioModelChanged: (modelId: string) => void;
  onSpeechConversationModelChanged: (modelId: string) => void;
};

export function createSettingsPanelState(): SettingsPanelState {
  return {
    agenticBindingErrors: {},
    cleanupError: '',
    clearingAllRuntime: false,
    cleaningSessionIds: new Set(),
    draftModelId: '',
    hostedDraftModelId: '',
    hostedProviderError: '',
    hostedProviderErrorModelId: '',
    hostedRoutingDraftsByModel: {},
    isSavingHostedProvider: false,
    isSavingProvider: false,
    isSavingSpeechProvider: false,
    isLoadingProviderUsage: false,
    isLoadingUsageHistory: false,
    savingAgenticBindings: new Set(),
    providerError: '',
    providerUsageError: '',
    providerUsageItems: [],
    hourlyUsage: null,
    dailyUsage: null,
    usageHistoryFilters: defaultUsageHistoryFilters(),
    usageHistoryError: '',
    speechAudioModelId: '',
    speechConversationModelId: '',
    speechProviderError: ''
  };
}

export function syncSettingsPanelDraft(state: SettingsPanelState, settings: PlatformSettings | null) {
  const { modelId } = selectedProviderDraft(settings);
  const { modelId: hostedModelId } = selectedHostedProviderDraft(settings);
  const speechDraft = selectedSpeechProviderDraft(settings);
  const hostedModelIds = new Set(hostedModelOptionsForSettings(settings).map((option) => option.model_id).filter(Boolean));
  if (hostedModelId) {
    hostedModelIds.add(hostedModelId);
  }
  state.draftModelId = modelId;
  state.hostedDraftModelId = hostedModelId;
  state.speechAudioModelId = speechDraft.audioModelId;
  state.speechConversationModelId = speechDraft.conversationModelId;
  state.hostedRoutingDraftsByModel = Object.fromEntries(
    Array.from(hostedModelIds).map((modelId) => [modelId, routingDraftFromRouting(openRouterRoutingForModel(settings, modelId))])
  );
}

export function updateDraftModel(state: SettingsPanelState, modelId: string) {
  state.draftModelId = modelId;
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
  const selectedOption = modelOptions.find((option) => option.model_id === state.draftModelId) || modelOptions[0] || null;
  const modelDefaultReasoning = defaultReasoningForOption(selectedOption);
  const openHostedModel = openHostedModelId(settings, state);
  const canSaveProvider = Boolean(
    provider &&
      state.draftModelId &&
      !state.isSavingProvider &&
      state.draftModelId !== selectedModel
  );

  return `${userSettingsCardHtml(settings)}
    ${agenticRuntimeSettingsCardHtml(settings.agentic_admin || null, state)}
    ${usageHistoryCardHtml(state)}
    ${settings.agentic_admin ? '' : agenticModelSettingsCardHtml(
        provider,
        modelOptions,
        modelDefaultReasoning,
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

function usageHistoryCardHtml(state: SettingsPanelState) {
  const refreshIcon = state.isLoadingUsageHistory ? 'sync' : 'refresh';
  return `<section class="settings-card settings-platform settings-usage-history-card" aria-labelledby="settings-usage-history-title">
    <div class="settings-heading settings-platform-heading settings-usage-history-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">monitoring</span>
      <div>
        <p class="settings-kicker">Workspace metering</p>
        <h2 id="settings-usage-history-title">Token usage history</h2>
      </div>
      <button type="button" class="settings-secondary settings-provider-usage-refresh" id="settings-refresh-usage-history" ${state.isLoadingUsageHistory ? 'disabled' : ''}>
        <span class="material-symbols-rounded ${state.isLoadingUsageHistory ? 'is-spinning' : ''}" aria-hidden="true">${refreshIcon}</span>
        Refresh
      </button>
    </div>
    <p class="settings-card-copy">Hourly and daily usage across root and delegated runtime sessions. Charts default to non-cached tokens; use the filters to inspect processed totals, cache, providers, models, and time ranges.</p>
    ${state.usageHistoryError ? `<p class="settings-inline-error" role="alert">${escapeHtml(state.usageHistoryError)}</p>` : ''}
    <div class="settings-usage-history-filters" data-usage-history-filters aria-label="Token history filters"></div>
    <div class="settings-usage-history-grid">
      <article class="settings-usage-history-panel">
        <div>
          <p class="settings-kicker">Last ${state.usageHistoryFilters.hourlyPeriods} hours</p>
          <h3>Hourly consumption</h3>
        </div>
        <div data-usage-history-chart="hour" aria-live="polite"></div>
      </article>
      <article class="settings-usage-history-panel">
        <div>
          <p class="settings-kicker">Last ${state.usageHistoryFilters.dailyPeriods} days</p>
          <h3>Daily consumption</h3>
        </div>
        <div data-usage-history-chart="day" aria-live="polite"></div>
      </article>
    </div>
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
  modelDefaultReasoning: string,
  canSaveProvider: boolean,
  activeRuntimeSessionCount: number,
  runtimeSessionCount: number,
  isOpen: boolean,
  state: SettingsPanelState
) {
  return `<section class="settings-card settings-platform settings-agentic-model-settings-card">
    ${modelSettingsHeadingHtml('memory', 'Agentic model settings')}
    <div class="settings-platform-provider-forms">
      ${providerSettingsFormHtml(provider, modelOptions, modelDefaultReasoning, canSaveProvider, activeRuntimeSessionCount, runtimeSessionCount, isOpen, state)}
      ${providerSubscriptionUsageHtml(provider, state)}
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
  document.querySelectorAll<HTMLButtonElement>('[data-agentic-binding-save]').forEach((button) => {
    button.addEventListener('click', () => {
      actions.onSaveAgenticBinding(
        button.dataset.agenticDefinitionId || '',
        button.dataset.agenticDefinitionRevision || ''
      );
    });
  });
  document.querySelectorAll<HTMLInputElement>('[data-agentic-model-toggle]').forEach((toggle) => {
    const toggleLabel = toggle.closest<HTMLElement>('.settings-bouncy-toggle');
    toggle.addEventListener('click', (event) => event.stopPropagation());
    toggle.closest('label')?.addEventListener('click', (event) => event.stopPropagation());
    toggle.addEventListener('change', () => {
      const enable = toggle.checked;
      const statusLabel = toggleLabel?.querySelector<HTMLElement>('.settings-bouncy-toggle__label');
      if (statusLabel) statusLabel.textContent = enable ? 'On' : 'Off';
      actions.onSaveAgenticBinding(
        toggle.dataset.agenticDefinitionId || '',
        toggle.dataset.agenticDefinitionRevision || '',
        { enabled: enable }
      );
    });
  });
  document.getElementById('settings-provider-model')?.addEventListener('change', (event) => {
    actions.onProviderModelChanged((event.currentTarget as HTMLSelectElement).value);
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
  document.getElementById('settings-refresh-provider-usage')?.addEventListener('click', actions.onRefreshProviderUsage);
  document.getElementById('settings-refresh-usage-history')?.addEventListener('click', actions.onRefreshProviderUsage);
  document.querySelectorAll<HTMLButtonElement>('[data-hosted-provider-save]').forEach((button) => {
    button.addEventListener('click', () => actions.onSaveHostedProviderSettings(button.dataset.hostedProviderSave || ''));
  });
  document.getElementById('settings-logout')?.addEventListener('click', actions.onLogout);
  document.getElementById('settings-clear-all-runtime')?.addEventListener('click', actions.onClearAllRuntimeSessions);
  document.querySelectorAll<HTMLButtonElement>('[data-runtime-clear]').forEach((button) => {
    button.addEventListener('click', () => actions.onClearRuntimeSession(button.dataset.runtimeClear || ''));
  });
}

function agenticRuntimeSettingsCardHtml(admin: AgenticAdminPayload | null, state: SettingsPanelState) {
  const visibleItems = admin?.items || [];
  const releaseDecision = admin?.release_decision || 'GO';
  return `<section class="settings-card settings-platform settings-agentic-runtimes-card">
    ${modelSettingsHeadingHtml('account_tree', 'Models')}
    <p class="settings-card-copy">Choose which models are available for new chats. Open a model only for optional workspace controls.</p>
    ${releaseDecision === 'NO-GO' ? `<p class="settings-platform-error settings-agentic-no-go"><strong>Remote agentic release: NO-GO</strong><br>Remote profiles remain visible for containment review but cannot be enabled or selected.</p>` : ''}
    ${visibleItems.some((item) => item.runtime_engine_id === 'codex') ? `<div class="settings-models-toolbar">
      <button type="button" class="settings-secondary settings-provider-usage-refresh" id="settings-refresh-provider-usage" ${state.isLoadingProviderUsage ? 'disabled' : ''}>
        <span class="material-symbols-rounded ${state.isLoadingProviderUsage ? 'is-spinning' : ''}" aria-hidden="true">${state.isLoadingProviderUsage ? 'sync' : 'refresh'}</span>
        Refresh limits
      </button>
    </div>` : ''}
    <div class="settings-agentic-runtime-list">
      ${visibleItems.length ? visibleItems.map((item) => agenticRuntimeBindingHtml(item, state)).join('') : `<div class="settings-provider-usage-unavailable">
        <span class="material-symbols-rounded" aria-hidden="true">block</span>
        <span><strong>No agentic definitions</strong><small>No certified runtime definitions are published by this installation.</small></span>
      </div>`}
    </div>
  </section>`;
}

function agenticRuntimeBindingHtml(item: AgenticAdminItem, state: SettingsPanelState) {
  const key = `${item.definition_id}:${item.definition_revision}`;
  const binding = item.binding;
  const policy = binding?.workspace_policy_ceiling || item.profile_policy_ceiling;
  const actor = binding?.actor_policy || {
    allow_workspace_admins: true,
    allowed_user_ids: [],
    allowed_workspace_role_ids: ['admin', 'member'],
    allowed_agent_type_ids: []
  };
  const certificate = item.certificate;
  const isRemote = item.runtime_engine_id !== 'codex';
  const contained = item.containment_status === 'NO-GO';
  const isSaving = state.savingAgenticBindings.has(key);
  const error = state.agenticBindingErrors[key] || '';
  const toolEnabled = policy.tool_handle_mode !== 'none';
  const costDollars = policy.max_estimated_cost_microusd === null
    ? ''
    : String(policy.max_estimated_cost_microusd / 1_000_000);
  const credentials = item.credential_bindings;
  const selectedCredential = binding?.credential_binding_id || credentials[0]?.binding_id || '';
  const enabled = Boolean(binding?.enabled);
  const available = !contained && certificate?.effective_status === 'active' && item.rollout_status !== 'disabled' && item.rollout_status !== 'suspended';
  const usageSummary = agenticModelUsageSummary(item, state);
  return `<details class="settings-model-accordion settings-agentic-runtime" data-settings-model-accordion="agentic-${escapeAttr(key)}">
    <summary>
      <span class="settings-model-summary-copy">
        <span class="settings-kicker">${escapeHtml(item.model_provider_id)}</span>
        <strong>${escapeHtml(item.display_name)}</strong>
        <small>${escapeHtml(item.model_id)}${binding?.is_default ? ' · Default' : ''}${usageSummary ? ` · ${escapeHtml(usageSummary)}` : ''}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        ${contained ? '<span class="settings-pill is-warning">NO-GO</span>' : ''}
        ${available ? '' : `<span class="settings-pill is-warning">${escapeHtml(humanizeAgenticCode(item.blocked_reason || certificate?.effective_status || 'Unavailable'))}</span>`}
        <label class="settings-model-toggle settings-toggle settings-bouncy-toggle" title="${enabled ? 'Disable model' : 'Enable model'}">
          <input type="checkbox" role="switch" data-agentic-model-toggle
            data-agentic-definition-id="${escapeAttr(item.definition_id)}"
            data-agentic-definition-revision="${escapeAttr(item.definition_revision)}"
            ${enabled ? 'checked' : ''} ${isSaving || (!available && !enabled) ? 'disabled' : ''}>
          <span class="settings-bouncy-toggle__label">${enabled ? 'On' : 'Off'}</span>
          <span class="settings-bouncy-toggle__track" aria-hidden="true">
            <span class="settings-bouncy-toggle__inner"></span>
            <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
          </span>
        </label>
      </span>
    </summary>
    <div class="settings-model-content settings-agentic-runtime-content" data-agentic-binding-form data-agentic-definition-id="${escapeAttr(item.definition_id)}" data-agentic-definition-revision="${escapeAttr(item.definition_revision)}">
      ${contained ? `<div class="settings-provider-usage-unavailable settings-agentic-containment-state">
        <span class="material-symbols-rounded" aria-hidden="true">block</span>
        <span>
          <strong>NO-GO · ${escapeHtml(humanizeAgenticCode(item.containment_reason || 'remote agentic contained'))}</strong>
          <small>Provider ${escapeHtml(item.model_provider_id)} · upstream ${escapeHtml(item.upstream_provider_ids.join(', ') || 'none')}</small>
          <small>Data destination ${escapeHtml(item.data_destination.display_label)}</small>
          <small>Egress policy ${escapeHtml(item.egress_policy.policy_id)}@${escapeHtml(item.egress_policy.revision)} · Core-classified data ${escapeHtml(item.egress_policy.allowed_remote_data_classes.join(', ') || 'none')}</small>
          <small>Data policy collection=${escapeHtml(item.data_policy.collection)} · ZDR ${item.data_policy.require_zdr ? 'required' : 'not required'} · attestation ${escapeHtml(item.data_policy.attestation_state)}</small>
          <small>Binding ${escapeHtml(humanizeAgenticCode(item.binding_status))} · Profile ${escapeHtml(humanizeAgenticCode(item.profile_status))} · Certificate ${escapeHtml(humanizeAgenticCode(certificate?.effective_status || 'missing'))} / ${escapeHtml(humanizeAgenticCode(item.certificate_eligibility))}</small>
        </span>
      </div>` : ''}
      <div class="settings-provider-usage-unavailable settings-agentic-capability-state">
        <span class="material-symbols-rounded" aria-hidden="true">verified_user</span>
        <span>
          <strong>Effective capabilities · ${escapeHtml(item.effective_capabilities.status)}</strong>
          <small>Snapshot ${escapeHtml(item.effective_capabilities.snapshot_digest)} · execution ${escapeHtml(item.effective_capabilities.execution_mode || 'unavailable')} · TCB ${escapeHtml(String(item.effective_capabilities.tcb?.posture || 'unavailable'))}</small>
          ${item.effective_capabilities.reason_code ? `<small>Reason ${escapeHtml(humanizeAgenticCode(item.effective_capabilities.reason_code))}</small>` : ''}
          <small>Filesystem read ${item.effective_capabilities.capabilities.filesystem_read === true ? 'yes' : 'no'} · write ${item.effective_capabilities.capabilities.filesystem_write === true ? 'yes' : 'no'} · shell ${item.effective_capabilities.capabilities.shell === true ? 'yes' : 'no'} · CLI ${item.effective_capabilities.capabilities.cli === true ? 'yes' : 'no'} · MCP ${item.effective_capabilities.capabilities.mcp === true ? 'yes' : 'no'}</small>
          <small>Skills ${item.effective_capabilities.capabilities.skill_catalog === true ? 'yes' : 'no'} · app references ${item.effective_capabilities.capabilities.app_references === true ? 'yes' : 'no'} · attachment modes ${escapeHtml(Array.isArray(item.effective_capabilities.capabilities.attachment_modalities) ? item.effective_capabilities.capabilities.attachment_modalities.join(', ') || 'none' : 'none')} · confirmations ${item.effective_capabilities.capabilities.confirmations === true ? 'yes' : 'no'} · recovery ${item.effective_capabilities.capabilities.recovery === true ? 'yes' : 'no'}</small>
          <small>Provider ${escapeHtml(item.effective_capabilities.provider?.provider_id || 'unavailable')} · upstream ${escapeHtml(item.effective_capabilities.provider?.effective_upstream_ids?.join(', ') || 'none')} · health ${escapeHtml(item.effective_capabilities.provider?.health_status || 'unavailable')}</small>
          <small>Data classes ${escapeHtml(item.effective_capabilities.data_policy?.allowed_remote_data_classes?.join(', ') || 'none')} · collection ${escapeHtml(item.effective_capabilities.data_policy?.collection || 'deny')} · ZDR ${item.effective_capabilities.data_policy?.require_zdr ? 'required' : 'not required'}</small>
          <small>Certificate ${escapeHtml(item.effective_capabilities.certificate?.certificate_id || 'unavailable')} · suite ${escapeHtml(item.effective_capabilities.certificate?.suite_id || 'unavailable')}@${escapeHtml(item.effective_capabilities.certificate?.suite_version || 'unavailable')} · expires ${escapeHtml(item.effective_capabilities.certificate?.expires_at || 'unavailable')}</small>
          <small>Workspace declaration (read-only): ${escapeHtml(item.data_policy.attestation_state)}${item.data_policy.attestation.revision === null ? '' : ` · revision ${item.data_policy.attestation.revision}`}${item.data_policy.attestation.scope ? ` · scope ${escapeHtml(item.data_policy.attestation.scope.resource_prefixes.join(', ') || 'workspace')}` : ''}</small>
        </span>
      </div>
      ${agenticModelUsageHtml(item, state)}
      <div class="settings-agentic-controls">
        ${isRemote ? `<label class="settings-platform-field">
          <span>Credential binding</span>
          <select data-agentic-field="credential_binding_id" ${isSaving || contained ? 'disabled' : ''}>
            <option value="">${credentials.length ? 'No credential' : 'No active credential available'}</option>
            ${credentials.map((credential) => `<option value="${escapeAttr(credential.binding_id)}" ${credential.binding_id === selectedCredential ? 'selected' : ''}>${escapeHtml(credential.label || credential.binding_id)} · ${credential.workspace_id ? 'workspace' : 'platform'}</option>`).join('')}
          </select>
        </label>` : '<input data-agentic-field="credential_binding_id" type="hidden" value="">'}
        <label class="settings-platform-field">
          <span>Maximum cost per turn (USD)</span>
          <input data-agentic-field="max_estimated_cost_usd" type="number" min="0" step="0.01" value="${escapeAttr(costDollars)}" placeholder="No explicit ceiling" ${isSaving || contained ? 'disabled' : ''}>
        </label>
        <div class="settings-platform-checks settings-agentic-checks">
          <input data-agentic-field="enabled" type="checkbox" ${enabled ? 'checked' : ''} hidden>
          ${agenticCheckbox('is_default', 'Use as workspace default', Boolean(binding?.is_default), isSaving || contained)}
          <details class="settings-agentic-advanced">
            <summary>Advanced controls</summary>
            ${agenticCheckbox('allow_workspace_admins', 'Workspace administrators', actor.allow_workspace_admins, isSaving || contained)}
            ${agenticCheckbox('allow_workspace_members', 'Workspace members', actor.allowed_workspace_role_ids.includes('member'), isSaving || contained)}
            ${agenticCheckbox('tool_access_enabled', `Allow tools (${policy.allowed_tool_handles.length || 0})`, toolEnabled, isSaving || contained)}
            ${agenticCheckbox('require_confirmation_for_mutating', 'Confirm mutating tools', policy.require_confirmation_for_mutating, isSaving || contained, item.profile_policy_ceiling.require_confirmation_for_mutating)}
            ${agenticCheckbox('require_confirmation_for_destructive', 'Confirm destructive tools', policy.require_confirmation_for_destructive, isSaving || contained, item.profile_policy_ceiling.require_confirmation_for_destructive)}
          </details>
        </div>
      </div>
      <button type="button" data-agentic-binding-save data-agentic-definition-id="${escapeAttr(item.definition_id)}" data-agentic-definition-revision="${escapeAttr(item.definition_revision)}" ${isSaving || contained ? 'disabled' : ''}>
        <span class="material-symbols-rounded" aria-hidden="true">${isSaving ? 'progress_activity' : 'verified_user'}</span>
        ${isSaving ? 'Saving binding' : binding ? 'Save binding' : 'Create binding'}
      </button>
      ${error ? `<p class="settings-platform-error" role="alert">${escapeHtml(error)}</p>` : ''}
    </div>
  </details>`;
}

function agenticCheckbox(field: string, label: string, checked: boolean, disabled: boolean, forced = false) {
  return bouncyToggleHtml(`<input data-agentic-field="${escapeAttr(field)}" type="checkbox" role="switch" ${checked ? 'checked' : ''} ${disabled || forced ? 'disabled' : ''}>`, escapeHtml(label));
}

function agenticModelUsageHtml(item: AgenticAdminItem, state: SettingsPanelState) {
  const usage = state.providerUsageItems.find((candidate) =>
    candidate.provider_id === item.runtime_engine_id || candidate.provider_id === item.model_provider_id
  );
  if (!usage?.available) {
    if (item.runtime_engine_id !== 'codex') return '';
    const message = state.isLoadingProviderUsage
      ? 'Reading package limits…'
      : state.providerUsageError
        ? 'Package limits are temporarily unavailable.'
        : 'Package limits have not been reported yet.';
    return `<div class="settings-agentic-usage-note"><span class="material-symbols-rounded" aria-hidden="true">speed</span>${escapeHtml(message)}</div>`;
  }
  const limits = agenticUsageLimits(item, usage);
  if (!limits.length) return '';
  return `<section class="settings-agentic-model-usage" aria-label="${escapeAttr(item.display_name)} usage limits">
    <div class="settings-agentic-model-usage-heading">
      <strong>Package limits</strong>
      <small>${usage.plan_type ? escapeHtml(usage.plan_type.replace(/[_-]+/g, ' ')) : 'Current subscription'}</small>
    </div>
    <div class="settings-provider-usage-limits">${limits.map(providerUsageLimitHtml).join('')}</div>
  </section>`;
}

function agenticModelUsageSummary(item: AgenticAdminItem, state: SettingsPanelState) {
  const usage = state.providerUsageItems.find((candidate) =>
    candidate.provider_id === item.runtime_engine_id || candidate.provider_id === item.model_provider_id
  );
  const limits = usage?.available ? agenticUsageLimits(item, usage) : [];
  const limit = limits.find((candidate) => !candidate.metered_feature) || limits[0] || null;
  const window = limit?.primary_window || limit?.secondary_window;
  if (!window) return '';
  const used = Math.round(Math.max(0, Math.min(100, window.used_percent)));
  return [`${used}% used`, formatUsageWindow(window.limit_window_seconds), formatUsageReset(window)].filter(Boolean).join(' · ');
}

function agenticUsageLimits(item: AgenticAdminItem, usage: ProviderSubscriptionUsage) {
  const modelKey = item.model_id.toLowerCase().replace(/[^a-z0-9]+/g, '');
  return usage.limits.filter((limit) => {
    const feature = (limit.metered_feature || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
    return !feature || feature === 'codex' || feature.includes(modelKey) || modelKey.includes(feature);
  });
}

function humanizeAgenticCode(value: string) {
  return value.replace(/[._-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

function providerSettingsFormHtml(
  provider: PlatformSettings['provider']['active_provider'] | null,
  modelOptions: ProviderModelOption[],
  modelDefaultReasoning: string,
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
        <small>${escapeHtml(state.draftModelId || 'model')} · per-chat reasoning · Codex tools/filesystem/MCP · ${activeRuntimeSessionCount} active / ${runtimeSessionCount} in scope</small>
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
    <p class="settings-card-copy">Reasoning is selected per chat. This model defaults to ${escapeHtml(modelDefaultReasoning || 'provider default')}.</p>
    <button type="button" id="settings-save-provider" ${canSaveProvider ? '' : 'disabled'}>
      <span class="material-symbols-rounded" aria-hidden="true">${state.isSavingProvider ? 'sync' : 'save'}</span>
      ${state.isSavingProvider ? 'Saving' : 'Save model'}
    </button>
    ${state.providerError ? `<p class="settings-platform-error">${escapeHtml(state.providerError)}</p>` : ''}
    </div>
  </details>`;
}

function providerSubscriptionUsageHtml(
  provider: PlatformSettings['provider']['active_provider'] | null,
  state: SettingsPanelState
) {
  if (!provider?.capabilities?.supports_subscription_usage) {
    return '';
  }
  const usage = state.providerUsageItems.find((item) => item.provider_id === provider.provider_id) || null;
  const plan = usage?.plan_type ? usage.plan_type.replace(/[_-]+/g, ' ') : '';
  const refreshIcon = state.isLoadingProviderUsage ? 'sync' : 'refresh';
  let content = '';
  if (state.isLoadingProviderUsage && !usage) {
    content = `<div class="settings-provider-usage-loading" role="status">
      <div data-provider-usage-gauge="0" data-provider-usage-indeterminate="true"></div>
      <span><strong>Reading subscription limits</strong><small>Refreshing usage directly from ${escapeHtml(provider.label)}.</small></span>
    </div>`;
  } else if (state.providerUsageError) {
    content = providerUsageUnavailableHtml('The current subscription usage could not be refreshed.');
  } else if (usage && !usage.available) {
    content = providerUsageUnavailableHtml(providerUsageUnavailableMessage(usage.unavailable_reason));
  } else if (!usage) {
    content = providerUsageUnavailableHtml('Usage has not been loaded yet.');
  } else if (!usage.limits.length) {
    content = providerUsageUnavailableHtml('This subscription did not report any active usage windows.');
  } else {
    content = `<div class="settings-provider-usage-limits">
      ${usage.limits.map(providerUsageLimitHtml).join('')}
    </div>`;
  }
  return `<section class="settings-provider-usage" aria-labelledby="settings-provider-usage-title">
    <div class="settings-provider-usage-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">speed</span>
      <span class="settings-provider-usage-title">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Subscription usage</span>
          ${plan ? `<span class="settings-provider-usage-plan">${escapeHtml(plan)}</span>` : ''}
        </span>
        <strong id="settings-provider-usage-title">Usage limits</strong>
        <small>${usage?.available ? `Updated ${escapeHtml(formatUsageTimestamp(usage.fetched_at))}` : 'Account-level usage, read securely by Maverick Core'}</small>
      </span>
      <button type="button" class="settings-secondary settings-provider-usage-refresh" id="settings-refresh-provider-usage" ${state.isLoadingProviderUsage ? 'disabled' : ''}>
        <span class="material-symbols-rounded ${state.isLoadingProviderUsage ? 'is-spinning' : ''}" aria-hidden="true">${refreshIcon}</span>
        Refresh
      </button>
    </div>
    ${content}
  </section>`;
}

function providerUsageLimitHtml(limit: ProviderUsageLimit) {
  const windows = [
    { label: limit.secondary_window ? 'Primary window' : '', window: limit.primary_window },
    { label: 'Secondary window', window: limit.secondary_window }
  ].filter((item): item is { label: string; window: ProviderUsageWindow } => Boolean(item.window));
  return windows.map(({ label, window }) => {
    const value = Math.round(Math.max(0, Math.min(100, window.used_percent)));
    const detail = [label, formatUsageWindow(window.limit_window_seconds), formatUsageReset(window)].filter(Boolean).join(' · ');
    return `<article class="settings-provider-usage-limit ${limit.limit_reached ? 'is-reached' : ''}">
      <div class="settings-provider-usage-gauge" data-provider-usage-gauge="${escapeAttr(String(value))}"></div>
      <span class="settings-provider-usage-limit-copy">
        <strong>${escapeHtml(limit.label)}</strong>
        <small>${escapeHtml(detail)}</small>
      </span>
      <span class="settings-provider-usage-value">
        <strong>${value}%</strong>
        <small>${limit.limit_reached ? 'limit reached' : 'used'}</small>
      </span>
    </article>`;
  }).join('');
}

function providerUsageUnavailableHtml(message: string) {
  return `<div class="settings-provider-usage-unavailable">
    <span class="material-symbols-rounded" aria-hidden="true">info</span>
    <span><strong>Usage unavailable</strong><small>${escapeHtml(message)}</small></span>
  </div>`;
}

function providerUsageUnavailableMessage(reason: string | null) {
  if (reason === 'authentication_required') {
    return 'Sign in to Codex on the Maverick host to read subscription usage.';
  }
  if (reason === 'usage_not_reported') {
    return 'The provider did not report a subscription usage window.';
  }
  return 'The provider usage service is temporarily unavailable.';
}

function formatUsageWindow(seconds: number | null) {
  if (!seconds || seconds <= 0) return '';
  if (seconds % 86400 === 0) {
    const days = seconds / 86400;
    return `${days}-day window`;
  }
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return `${hours}-hour window`;
  }
  return 'rolling window';
}

function formatUsageReset(window: ProviderUsageWindow) {
  const seconds = window.reset_after_seconds;
  if (seconds !== null && seconds >= 0) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    if (days > 0) return `resets in ${days}d ${hours}h`;
    const minutes = Math.max(1, Math.floor((seconds % 3600) / 60));
    return hours > 0 ? `resets in ${hours}h ${minutes}m` : `resets in ${minutes}m`;
  }
  if (window.reset_at_epoch_seconds) {
    return `resets ${new Date(window.reset_at_epoch_seconds * 1000).toLocaleString()}`;
  }
  return '';
}

function formatUsageTimestamp(value: string) {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? 'recently' : timestamp.toLocaleString();
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
      ${bouncyToggleHtml(`<input type="checkbox" role="switch" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${escapeAttr(modelId)}" ${draft.allowFallbacks ? 'checked' : ''} ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}>`, 'Allow OpenRouter fallback')}
      ${bouncyToggleHtml(`<input type="checkbox" role="switch" data-openrouter-routing="require_parameters" data-hosted-model-id="${escapeAttr(modelId)}" ${draft.requireParameters ? 'checked' : ''} ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}>`, 'Require supported parameters')}
      ${bouncyToggleHtml(`<input type="checkbox" role="switch" data-openrouter-routing="zdr" data-hosted-model-id="${escapeAttr(modelId)}" ${draft.zdr ? 'checked' : ''} ${!hasHostedProvider || state.isSavingHostedProvider ? 'disabled' : ''}>`, 'Require zero data retention')}
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
      ${session.status === 'recovery_required' ? `<small class="settings-platform-error">Quarantined: ${escapeHtml(humanizeAgenticCode(session.recovery_reason_code || 'runtime state ambiguous'))}</small>` : ''}
      ${session.agentic_containment?.status === 'NO-GO' ? `<small class="settings-platform-error">Pinned remote profile contained (NO-GO): ${escapeHtml(humanizeAgenticCode(session.agentic_containment.reason_code || 'remote agentic contained'))}</small>` : ''}
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
    zdr: routing?.zdr === true,
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
    (saved.zdr === true) !== (draft.zdr === true) ||
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
