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
  providerError: string;
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
    providerError: ''
  };
}

export function syncSettingsPanelDraft(state: SettingsPanelState, settings: PlatformSettings | null) {
  const { modelId, reasoningEffort } = selectedProviderDraft(settings);
  const { modelId: hostedModelId } = selectedHostedProviderDraft(settings);
  const hostedModelIds = new Set(hostedModelOptionsForSettings(settings).map((option) => option.model_id).filter(Boolean));
  if (hostedModelId) {
    hostedModelIds.add(hostedModelId);
  }
  state.draftModelId = modelId;
  state.draftReasoningEffort = reasoningEffort;
  state.hostedDraftModelId = hostedModelId;
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
  const runtimeSessions = scopedRuntimeSessions(settings);
  const activeRuntimeSessions = runtimeSessions.filter((session) => ACTIVE_RUNTIME_STATUSES.has(session.status));
  const cleanupAllowed = settings.runtime.cleanup_allowed ?? false;
  const cleanupScope = settings.runtime.cleanup_scope || 'none';
  const modelOptions = modelOptionsForSettings(settings);
  const hostedModelOptions = hostedModelOptionsForSettings(settings);
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
    ${modelSettingsCardHtml(
      provider,
      modelOptions,
      reasoningOptions,
      canSaveProvider,
      activeRuntimeSessions.length,
      runtimeSessions.length,
      openHostedModel,
      hostedModelOptions,
      hostedProvider,
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

function modelSettingsCardHtml(
  provider: PlatformSettings['provider']['active_provider'] | null,
  modelOptions: ProviderModelOption[],
  reasoningOptions: ProviderModelOption['supported_reasoning_efforts'],
  canSaveProvider: boolean,
  activeRuntimeSessionCount: number,
  runtimeSessionCount: number,
  openHostedModel: string,
  hostedModelOptions: ProviderModelOption[],
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  return `<section class="settings-card settings-platform settings-model-settings-card">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Models</p>
        <h2>Model settings</h2>
      </div>
    </div>
    <div class="settings-platform-provider-forms">
      ${providerSettingsFormHtml(provider, modelOptions, reasoningOptions, canSaveProvider, activeRuntimeSessionCount, runtimeSessionCount, !openHostedModel, state)}
      ${hostedProviderSettingsListHtml(hostedModelOptions, openHostedModel, hostedProvider, settings, state)}
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

function hostedProviderSettingsListHtml(
  modelOptions: ProviderModelOption[],
  openHostedModel: string,
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  const hasHostedProvider = Boolean(hostedProvider);
  return `<div class="settings-hosted-models">
    <div class="settings-platform-form-heading settings-hosted-models-heading">
      <span class="material-symbols-rounded" aria-hidden="true">route</span>
      <span>
        <strong>Hosted OpenRouter models</strong>
        <small>Settings manages model defaults and upstream routing; Chat only uses text-output fast models.</small>
      </span>
    </div>
    ${
      modelOptions.length
        ? modelOptions.map((option) => hostedProviderModelAccordionHtml(option, openHostedModel, hostedProvider, settings, state)).join('')
        : '<p class="settings-card-copy settings-platform-note">No hosted models are available from the active hosted provider.</p>'
    }
    ${!hasHostedProvider ? '<p class="settings-card-copy settings-platform-note">Activate a hosted text provider before selecting a fast model.</p>' : ''}
  </div>`;
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
  const quantizations = Array.from(new Set(upstreamOptions.map((option) => option.quantization || '').filter(Boolean)));
  const hasHostedProvider = Boolean(hostedProvider);
  const isSavingThisModel = state.isSavingHostedProvider && state.hostedDraftModelId === modelId;
  const canSaveProvider = Boolean(
    hasHostedProvider &&
      modelId &&
      !state.isSavingHostedProvider &&
      hostedRoutingChanged(state, settings, modelId)
  );
  const isTextOutputModel = modelSupportsTextOutput(option);
  const modelKindLabel = isTextOutputModel ? 'Hosted chat / fast model' : 'Hosted speech model';
  const modelRuntimeLabel = isTextOutputModel
    ? 'plain hosted chat capable · runtime engine remains Codex'
    : 'speech synthesis metadata · not used by plain hosted chat';
  const isOpen = modelId === openHostedModel;
  const providerLabel = hostedProvider?.label || hostedProvider?.provider_id || 'Hosted provider';
  return `<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${escapeAttr(modelId)}" data-hosted-model-accordion="${escapeAttr(modelId)}" ${isOpen ? 'open' : ''}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">bolt</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${modelKindLabel}</span>
          <span class="settings-pill">Active</span>
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
    <button type="button" data-hosted-provider-save="${escapeAttr(modelId)}" ${canSaveProvider ? '' : 'disabled'}>
      <span class="material-symbols-rounded" aria-hidden="true">${isSavingThisModel ? 'sync' : 'save'}</span>
      ${isSavingThisModel ? 'Saving' : 'Save hosted model'}
    </button>
    ${state.hostedProviderError && state.hostedProviderErrorModelId === modelId ? `<p class="settings-platform-error">${escapeHtml(state.hostedProviderError)}</p>` : ''}
    </div>
  </details>`;
}

function modelSupportsTextOutput(option: ProviderModelOption): boolean {
  const outputs = option.output_modalities || [];
  return !outputs.length || outputs.includes('text');
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
