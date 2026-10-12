import type { PlatformSettings, ProviderModelOption } from './adminApi';
import { hostedRoutingDraftForModel, hostedRoutingChanged, type SettingsPanelState } from './settingsDrafts';
import { escapeHtml, escapeAttr } from './html';
import { bouncyToggleHtml } from './bouncyToggle';

type HostedProviderModelGroup = {
  providerId: string;
  providerLabel: string;
  providerStatus: string;
  models: ProviderModelOption[];
};

export function hostedProviderSettingsListHtml({
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
  const isOpen = modelId === openHostedModel;
  const providerLabel = hostedProviderLabelForModel(option, hostedProvider);
  return `<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${escapeAttr(modelId)}" data-hosted-model-accordion="${escapeAttr(modelId)}" id="settings-hosted-${escapeAttr(encodeURIComponent(modelId))}" ${isOpen ? 'open' : ''}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">record_voice_over</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Hosted speech model</span>
        </span>
        <strong>${escapeHtml(option.label || modelId)} - ${escapeHtml(providerLabel)}</strong>
        <small>${escapeHtml(modelId || 'model not selected')} · speech synthesis metadata</small>
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

