import type { AgenticAdminItem, AgenticAdminPayload, ExecutionFamilyDefinition, NativeAgentStatus } from './adminApi';
import type { SettingsPanelState } from './settingsDrafts';
import { escapeHtml, escapeAttr } from './html';
import { bouncyToggleHtml } from './bouncyToggle';
import { executionFamily } from './executionFamilies';
type RuntimeProviderEntry = { html: string; providerId: string; providerLabel: string; canActivate?: boolean };

export function modelSettingsHeadingHtml(icon: string, title: string) {
  return `<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(icon)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${escapeHtml(title)}</h2>
      </div>
    </div>`;
}

export function agenticRuntimeSettingsCardHtml(
  admin: AgenticAdminPayload | null,
  state: SettingsPanelState,
  projectedFamilies: ExecutionFamilyDefinition[] | undefined,
  nativeAgents: NativeAgentStatus[],
  canManageProviders: boolean
) {
  const activatableIds = new Set(nativeAgents.filter((item) =>
    canManageProviders && item.runtime_engine_id !== 'codex'
      && item.unavailable_reason === 'native_agent_disabled' && item.models.length > 0
  ).map((item) => item.runtime_engine_id));
  const allItems = admin?.items || [];
  const visibleItems = allItems;
  const releaseDecision = admin?.release_decision || 'GO';
  const nativeFamily = executionFamily('native_agent', projectedFamilies || admin?.execution_families);
  const maverickFamily = executionFamily('maverick_agent', projectedFamilies || admin?.execution_families);
  const nativeItems = visibleItems.filter((item) =>
    item.execution_family === 'native_agent'
      || (!item.execution_family && item.runtime_engine_id === 'codex')
  );
  const maverickItems = visibleItems.filter((item) => item.execution_family === 'maverick_agent');
  const representedNativeIds = new Set(allItems.filter((item) =>
    item.execution_family === 'native_agent'
      || (!item.execution_family && item.runtime_engine_id === 'codex')
  ).map((item) => item.runtime_engine_id));
  const standaloneNativeAgents = nativeAgents.filter(
    (item) => !representedNativeIds.has(item.runtime_engine_id)
  );
  const nativeEntries: RuntimeProviderEntry[] = [
    ...collapseAntigravityEffortProfiles(nativeItems).map((item) => ({
      html: agenticRuntimeBindingHtml(item, state),
      providerId: item.runtime_engine_id,
      canActivate: activatableIds.has(item.runtime_engine_id),
      providerLabel: runtimeProviderLabel(item.runtime_engine_id)
    })),
    ...standaloneNativeAgents.map((item) => ({
      html: nativeAgentInstallationHtml(item),
      providerId: item.runtime_engine_id,
      canActivate: activatableIds.has(item.runtime_engine_id),
      providerLabel: item.label || runtimeProviderLabel(item.runtime_engine_id)
    }))
  ];
  const maverickEntries = maverickItems.map((item) => ({
    html: agenticRuntimeBindingHtml(item, state),
    providerId: item.model_provider_id,
    providerLabel: runtimeProviderLabel(item.model_provider_id)
  }));
  return `<section class="settings-card settings-platform settings-agentic-runtimes-card">
    ${modelSettingsHeadingHtml('account_tree', 'Models')}
    ${releaseDecision === 'NO-GO' ? `<p class="settings-platform-error settings-agentic-no-go"><strong>Remote agentic release: NO-GO</strong><br>Remote profiles remain visible for containment review but cannot be enabled or selected.</p>` : ''}
    ${runtimeFamilySectionHtml(
      nativeFamily,
      nativeEntries,
      state,
      'No native-agent runtime is registered by this installation.'
    )}
    ${runtimeFamilySectionHtml(
      maverickFamily,
      maverickEntries,
      state,
      'No complete Maverick Agent profile is currently available.'
    )}
  </section>`;
}

function runtimeFamilySectionHtml(
  family: ExecutionFamilyDefinition,
  entries: RuntimeProviderEntry[],
  state: SettingsPanelState,
  emptyMessage: string
) {
  const groups = runtimeProviderGroups(entries);
  return `<section class="settings-runtime-family" data-execution-family="${escapeAttr(family.family_id)}">
    <header class="settings-runtime-family-heading">
      <h3>${escapeHtml(family.label)}</h3>
    </header>
    <div class="settings-runtime-provider-list">
      ${groups.length ? groups.map((group) => runtimeProviderGroupHtml(group, state)).join('') : `<div class="settings-provider-usage-unavailable">
        <span class="material-symbols-rounded" aria-hidden="true">info</span>
        <span><strong>No available profiles</strong><small>${escapeHtml(emptyMessage)}</small></span>
      </div>`}
    </div>
  </section>`;
}

function runtimeProviderGroups(entries: RuntimeProviderEntry[]) {
  const groups = new Map<string, RuntimeProviderEntry[]>();
  entries.forEach((entry) => {
    const current = groups.get(entry.providerId) || [];
    current.push(entry);
    groups.set(entry.providerId, current);
  });
  const order = new Map([
    ['codex', 0],
    ['antigravity-cli', 1],
    ['openrouter', 2],
    ['google-ai-studio', 3]
  ]);
  return Array.from(groups.entries())
    .map(([providerId, items]) => ({
      providerId,
      providerLabel: items[0]?.providerLabel || runtimeProviderLabel(providerId),
      items
    }))
    .sort((left, right) =>
      (order.get(left.providerId) ?? 100) - (order.get(right.providerId) ?? 100)
      || left.providerLabel.localeCompare(right.providerLabel)
    );
}

function runtimeProviderGroupHtml(
  group: ReturnType<typeof runtimeProviderGroups>[number],
  state: SettingsPanelState
) {
  const canActivate = group.items.some((item) => item.canActivate);
  const activating = state.activatingNativeProviders.has(group.providerId);
  const error = state.nativeProviderErrors[group.providerId];
  return `<section class="settings-runtime-provider" data-agentic-provider-group="${escapeAttr(group.providerId)}">
    <header class="settings-runtime-provider-heading">
      <h4>${escapeHtml(group.providerLabel)}</h4>

    </header>
    ${canActivate ? `<div class="settings-native-provider-activation">
      <span>Connection disabled. Enable it for this installation to use the selected models.</span>
      <button type="button" data-native-provider-activate="${escapeAttr(group.providerId)}" ${activating ? 'disabled' : ''}>
        ${activating ? 'Enabling…' : `Enable ${escapeHtml(group.providerLabel)}`}
      </button>
    </div>` : ''}
    ${error ? `<p class="settings-platform-error" role="alert">${escapeHtml(error)}</p>` : ''}
    <div class="settings-agentic-runtime-list">${group.items.map((item) => item.html).join('')}</div>
  </section>`;
}

function runtimeProviderLabel(providerId: string): string {
  const labels: Record<string, string> = {
    'antigravity-cli': 'Antigravity',
    'codex': 'Codex',
    'google-ai-studio': 'Google AI Studio',
    'openrouter': 'OpenRouter'
  };
  return labels[providerId] || humanizeAgenticCode(providerId);
}

function collapseAntigravityEffortProfiles(items: AgenticAdminItem[]): AgenticAdminItem[] {
  const selected = new Map<string, AgenticAdminItem>();
  const order: string[] = [];
  items.forEach((item) => {
    const baseModelId = item.runtime_engine_id === 'antigravity-cli'
      ? item.model_id.replace(/-(high|medium|low)$/i, '')
      : item.model_id;
    const key = `${item.runtime_engine_id}\0${baseModelId}`;
    if (!selected.has(key)) {
      order.push(key);
    }
    const current = selected.get(key);
    if (!current || antigravityEffortRank(item.model_id) > antigravityEffortRank(current.model_id)) {
      selected.set(key, item);
    }
  });
  return order.map((key) => selected.get(key)).filter((item): item is AgenticAdminItem => Boolean(item));
}

function antigravityEffortRank(modelId: string): number {
  const effort = modelId.match(/-(high|medium|low)$/i)?.[1]?.toLowerCase();
  return effort === 'high' ? 3 : effort === 'medium' ? 2 : effort === 'low' ? 1 : 0;
}

function nativeAgentInstallationHtml(item: NativeAgentStatus) {
  const model = item.models[0];
  const reason = item.unavailable_reason || 'native_agent_unavailable';
  const available = item.selectable === true;
  return `<article class="settings-agentic-runtime settings-native-runtime-installation settings-agentic-runtime-static">
    <div class="settings-agentic-runtime-static__content">
      <span class="settings-model-summary-copy">
        <strong>${escapeHtml(model?.model_id || item.label)}</strong>
        <small>${escapeHtml(reasoningSummary(model?.model_id, null))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        <span class="settings-pill ${available ? 'is-healthy' : 'is-warning'}">${available ? 'Available' : escapeHtml(humanizeAgenticCode(reason))}</span>
      </span>
    </div>
  </article>`;
}

function agenticRuntimeBindingHtml(item: AgenticAdminItem, state: SettingsPanelState) {
  const key = item.definition_id;
  const binding = item.binding;
  const policy = binding?.workspace_policy_ceiling || item.profile_policy_ceiling;
  const actor = binding?.actor_policy || {
    allow_workspace_admins: true,
    allowed_user_ids: [],
    allowed_workspace_role_ids: ['admin', 'member'],
    allowed_agent_type_ids: []
  };
  const isRemote = item.execution_family === 'maverick_agent';
  const effectiveCapabilities = item.effective_capabilities;
  const contained = item.containment_status === 'NO-GO';
  const isSaving = state.savingAgenticBindings.has(key);
  const error = state.agenticBindingErrors[key] || '';
  const costDollars = policy.max_estimated_cost_microusd === null
    ? ''
    : String(policy.max_estimated_cost_microusd / 1_000_000);
  const credentials = item.credential_bindings;
  const selectedCredential = binding?.credential_binding_id || credentials[0]?.binding_id || '';
  const enabled = state.pendingAgenticEnabled[key] ?? Boolean(binding?.enabled);
  const available = item.selectable === true || (!enabled && item.enable_eligible === true);
  const unavailableReason = item.enable_blocked_reason
    || item.blocked_reason
    || (isRemote && effectiveCapabilities?.status !== 'active'
      ? effectiveCapabilities?.reason_code || 'effective capabilities unavailable'
      : '')
    || 'Unavailable';
  return `<details class="settings-model-accordion settings-agentic-runtime" data-settings-model-accordion="agentic-${escapeAttr(key)}">
    <summary>
      <span class="settings-model-summary-copy">
        <strong>${escapeHtml(agenticModelLabel(item))}</strong>
        <small>${escapeHtml(reasoningSummary(item.model_id, item.default_reasoning_effort))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        ${binding?.is_default ? '<span class="settings-pill">Default</span>' : ''}
        ${contained ? '<span class="settings-pill is-warning">NO-GO</span>' : ''}
        ${available ? '' : `<span class="settings-pill is-warning">${escapeHtml(humanizeAgenticCode(unavailableReason))}</span>`}
        <label class="settings-model-toggle settings-toggle settings-bouncy-toggle" title="${enabled ? 'Disable model' : 'Enable model'}">
          <input type="checkbox" role="switch" data-agentic-model-toggle data-settings-controlled aria-label="Enable ${escapeAttr(agenticModelLabel(item))}"
            data-agentic-definition-id="${escapeAttr(item.definition_id)}"
            ${enabled ? 'checked' : ''} ${isSaving || (item.enable_eligible !== true && !enabled) ? 'disabled' : ''}>
          <span class="settings-bouncy-toggle__label">${enabled ? 'On' : 'Off'}</span>
          <span class="settings-bouncy-toggle__track" aria-hidden="true">
            <span class="settings-bouncy-toggle__inner"></span>
            <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
          </span>
        </label>
      </span>
    </summary>
    <div class="settings-model-content settings-agentic-runtime-content" data-agentic-binding-form data-agentic-definition-id="${escapeAttr(item.definition_id)}">
      ${contained ? `<div class="settings-provider-usage-unavailable settings-agentic-containment-state">
        <span class="material-symbols-rounded" aria-hidden="true">block</span>
        <span>
          <strong>NO-GO · ${escapeHtml(humanizeAgenticCode(item.containment_reason || 'remote agentic contained'))}</strong>
          <small>${escapeHtml(item.data_destination.display_label)}</small>
        </span>
      </div>` : ''}
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
            ${agenticCheckbox('require_confirmation_for_mutating', 'Confirm mutating tools', policy.require_confirmation_for_mutating, isSaving || contained, item.profile_policy_ceiling.require_confirmation_for_mutating)}
            ${agenticCheckbox('require_confirmation_for_destructive', 'Confirm destructive tools', policy.require_confirmation_for_destructive, isSaving || contained, item.profile_policy_ceiling.require_confirmation_for_destructive)}
          </details>
        </div>
      </div>
      <button type="button" data-agentic-binding-save data-agentic-definition-id="${escapeAttr(item.definition_id)}" ${isSaving || contained ? 'disabled' : ''}>
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

function agenticModelLabel(item: AgenticAdminItem): string {
  if (item.runtime_engine_id === 'codex' || item.runtime_engine_id === 'antigravity-cli') {
    return item.model_id;
  }
  return item.display_name
    .replace(/^OpenRouter\s+/i, '')
    .replace(/^Google\s+/i, '')
    .replace(/\s+·\s+Relace$/i, '');
}

function reasoningSummary(modelId: string | undefined, defaultEffort: string | null | undefined): string {
  const inferred = modelId?.match(/-(max|xhigh|high|medium|low)$/i)?.[1] || '';
  const effort = defaultEffort || inferred;
  return `Reasoning · ${effort ? humanizeAgenticCode(effort) : 'Preset'}`;
}

function humanizeAgenticCode(value: string) {
  return value.replace(/[._-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}
