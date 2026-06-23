import type { PlatformSettings, ProviderModelOption, RuntimeSessionItem } from './adminApi';
import {
  defaultReasoningForOption,
  hostedModelOptionsForSettings,
  modelOptionsForSettings,
  selectedHostedProviderDraft,
  selectedProviderDraft
} from './providerModelOptions';

const ACTIVE_RUNTIME_STATUSES = new Set(['created', 'running', 'stopping']);

export type SettingsPanelState = {
  cleanupError: string;
  clearingAllRuntime: boolean;
  cleaningSessionIds: Set<string>;
  draftModelId: string;
  draftReasoningEffort: string;
  hostedDraftModelId: string;
  hostedProviderError: string;
  isSavingHostedProvider: boolean;
  isSavingProvider: boolean;
  providerError: string;
};

export type SettingsPanelActions = {
  onClearAllRuntimeSessions: () => void;
  onClearRuntimeSession: (sessionId: string) => void;
  onLogout: () => void;
  onHostedProviderModelChanged: (modelId: string) => void;
  onSaveHostedProviderSettings: () => void;
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
    isSavingHostedProvider: false,
    isSavingProvider: false,
    providerError: ''
  };
}

export function syncSettingsPanelDraft(state: SettingsPanelState, settings: PlatformSettings | null) {
  const { modelId, reasoningEffort } = selectedProviderDraft(settings);
  const { modelId: hostedModelId } = selectedHostedProviderDraft(settings);
  state.draftModelId = modelId;
  state.draftReasoningEffort = reasoningEffort;
  state.hostedDraftModelId = hostedModelId;
}

export function updateDraftModel(state: SettingsPanelState, settings: PlatformSettings | null, modelId: string) {
  const option = modelOptionsForSettings(settings).find((item) => item.model_id === modelId) || null;
  state.draftModelId = modelId;
  state.draftReasoningEffort = defaultReasoningForOption(option);
  state.providerError = '';
}

export function updateHostedDraftModel(state: SettingsPanelState, modelId: string) {
  state.hostedDraftModelId = modelId;
  state.hostedProviderError = '';
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
  const selectedHostedModel = selectedHostedProviderDraft(settings).modelId;
  const selectedOption = modelOptions.find((option) => option.model_id === state.draftModelId) || modelOptions[0] || null;
  const reasoningOptions = selectedOption?.supported_reasoning_efforts || [];
  const canSaveProvider = Boolean(
    provider &&
      state.draftModelId &&
      !state.isSavingProvider &&
      (state.draftModelId !== selectedModel || state.draftReasoningEffort !== selectedReasoning)
  );
  const canSaveHostedProvider = Boolean(
    hostedProvider &&
      state.hostedDraftModelId &&
      !state.isSavingHostedProvider &&
      state.hostedDraftModelId !== selectedHostedModel
  );

  return `<section class="settings-card settings-platform">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Settings</p>
        <h2>Platform settings</h2>
      </div>
    </div>
    <div class="settings-platform-grid">
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
      <article class="settings-platform-tile settings-platform-provider">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
        <div>
          <p class="settings-kicker">Agentic provider</p>
          <h3>${escapeHtml(provider?.label || 'Provider not loaded')}</h3>
          <p>${escapeHtml(selectedModel || 'model')} · ${escapeHtml(selectedReasoning || 'reasoning')} · Codex tools/filesystem/MCP · ${activeRuntimeSessions.length} active / ${runtimeSessions.length} in scope</p>
        </div>
      </article>
      <article class="settings-platform-tile settings-platform-provider">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">bolt</span>
        <div>
          <p class="settings-kicker">Hosted chat / fast model</p>
          <h3>${escapeHtml(hostedProvider?.label || 'No hosted text provider')}</h3>
          <p>${escapeHtml(selectedHostedModel || 'model not selected')} · plain hosted chat only · runtime engine remains Codex</p>
        </div>
      </article>
    </div>
    <div class="settings-platform-provider-forms">
      ${providerSettingsFormHtml(modelOptions, reasoningOptions, canSaveProvider, state)}
      ${hostedProviderSettingsFormHtml(hostedModelOptions, canSaveHostedProvider, state, Boolean(hostedProvider))}
    </div>
    ${runtimeSessionsHtml(runtimeSessions, cleanupAllowed, cleanupScope, state)}
  </section>`;
}

export function bindSettingsPanelEvents(actions: SettingsPanelActions) {
  document.getElementById('settings-provider-model')?.addEventListener('change', (event) => {
    actions.onProviderModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('settings-provider-reasoning')?.addEventListener('change', (event) => {
    actions.onProviderReasoningChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('settings-hosted-provider-model')?.addEventListener('change', (event) => {
    actions.onHostedProviderModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.getElementById('settings-save-provider')?.addEventListener('click', actions.onSaveProviderSettings);
  document.getElementById('settings-save-hosted-provider')?.addEventListener('click', actions.onSaveHostedProviderSettings);
  document.getElementById('settings-logout')?.addEventListener('click', actions.onLogout);
  document.getElementById('settings-clear-all-runtime')?.addEventListener('click', actions.onClearAllRuntimeSessions);
  document.querySelectorAll<HTMLButtonElement>('[data-runtime-clear]').forEach((button) => {
    button.addEventListener('click', () => actions.onClearRuntimeSession(button.dataset.runtimeClear || ''));
  });
}

function providerSettingsFormHtml(
  modelOptions: ProviderModelOption[],
  reasoningOptions: ProviderModelOption['supported_reasoning_efforts'],
  canSaveProvider: boolean,
  state: SettingsPanelState
) {
  return `<div class="settings-platform-provider-form">
    <div class="settings-platform-form-heading">
      <span class="material-symbols-rounded" aria-hidden="true">terminal</span>
      <span>
        <strong>Codex agent model</strong>
        <small>Agentic sessions, tools, filesystem, MCP and skills</small>
      </span>
    </div>
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
  </div>`;
}

function hostedProviderSettingsFormHtml(
  modelOptions: ProviderModelOption[],
  canSaveProvider: boolean,
  state: SettingsPanelState,
  hasHostedProvider: boolean
) {
  return `<div class="settings-platform-provider-form">
    <div class="settings-platform-form-heading">
      <span class="material-symbols-rounded" aria-hidden="true">route</span>
      <span>
        <strong>Hosted chat fast model</strong>
        <small>Hosted text providers govern plain_hosted_chat and fast_model only</small>
      </span>
    </div>
    <label class="settings-platform-field settings-platform-field-wide">
      <span>Model</span>
      <select id="settings-hosted-provider-model" ${!hasHostedProvider || !modelOptions.length || state.isSavingHostedProvider ? 'disabled' : ''}>
        ${modelOptions.map((option) => `<option value="${escapeAttr(option.model_id)}" ${option.model_id === state.hostedDraftModelId ? 'selected' : ''}>${escapeHtml(option.label || option.model_id)}</option>`).join('')}
      </select>
    </label>
    <button type="button" id="settings-save-hosted-provider" ${canSaveProvider ? '' : 'disabled'}>
      <span class="material-symbols-rounded" aria-hidden="true">${state.isSavingHostedProvider ? 'sync' : 'save'}</span>
      ${state.isSavingHostedProvider ? 'Saving' : 'Save hosted model'}
    </button>
    ${!hasHostedProvider ? '<p class="settings-card-copy settings-platform-note">Activate a hosted text provider before selecting a fast model.</p>' : ''}
    ${state.hostedProviderError ? `<p class="settings-platform-error">${escapeHtml(state.hostedProviderError)}</p>` : ''}
  </div>`;
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
  return `<details class="settings-platform-runtime" open>
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
  </details>`;
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
