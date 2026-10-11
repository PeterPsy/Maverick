import { requestJson, type ComputerUseSettings, type PlatformSettings } from './adminApi';
import { escapeHtml } from './html';

export type ComputerUseDraft = {
  workspaceId: string;
  providerId: string;
  modelId: string;
  effort: string;
  executionMode: 'direct' | 'delegated';
  fallbackModelId: string;
  fallbackEffort: string;
  saving: boolean;
  error: string;
  generation: number;
  savedSelection: string;
};

export function createComputerUseDraft(): ComputerUseDraft {
  return { workspaceId: '', providerId: '', modelId: '', effort: '', executionMode: 'delegated',
    fallbackModelId: '', fallbackEffort: '', saving: false, error: '', generation: 0, savedSelection: '' };
}

export function syncComputerUseDraft(state: ComputerUseDraft, settings: PlatformSettings | null, replaceDraft = false) {
  const selection = settings?.computer_use;
  const workspaceId = settings?.workspace.workspace_id || '';
  const workspaceChanged = state.workspaceId !== workspaceId;
  const savedSelection = JSON.stringify([selection?.provider_id, selection?.model_id, selection?.reasoning_effort,
    selection?.execution_mode, selection?.fallback_model_id, selection?.fallback_reasoning_effort]);
  if (workspaceChanged) {
    state.generation += 1;
    state.saving = false;
    state.error = '';
  }
  if (!workspaceChanged && state.savedSelection === savedSelection && !replaceDraft) return;
  Object.assign(state, { workspaceId, providerId: selection?.provider_id || '',
    modelId: selection?.model_id || '', effort: selection?.reasoning_effort || '',
    executionMode: selection?.execution_mode || 'delegated', fallbackModelId: selection?.fallback_model_id || '',
    fallbackEffort: selection?.fallback_reasoning_effort || '', savedSelection });
}

function selectedModel(settings: PlatformSettings | null, state: ComputerUseDraft) {
  return settings?.computer_use?.providers.find((provider) => provider.provider_id === state.providerId)
    ?.models.find((model) => model.model_id === state.modelId);
}

export function computerUseSettingsHtml(settings: PlatformSettings, state: ComputerUseDraft) {
  const selection = settings.computer_use;
  if (!selection) return '';
  const model = selectedModel(settings, state);
  const efforts = model?.supported_reasoning_efforts || [];
  const validEffort = efforts.length ? efforts.some((item) => item.effort === state.effort) : !state.effort;
  const changed = state.providerId !== selection.provider_id || state.modelId !== selection.model_id
    || state.effort !== (selection.reasoning_effort || '') || state.executionMode !== (selection.execution_mode || 'delegated')
    || state.fallbackModelId !== (selection.fallback_model_id || '') || state.fallbackEffort !== (selection.fallback_reasoning_effort || '');
  const disabled = !selection.can_configure || state.saving;
  return `<section class="settings-card settings-platform" aria-labelledby="settings-computer-use-title">
    <div class="settings-heading settings-platform-heading settings-model-card-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">desktop_windows</span>
      <div><p class="settings-kicker">Models</p><h2 id="settings-computer-use-title">PC use decision model</h2></div>
    </div>
    <p class="settings-card-copy">Use the chat model directly or a separate interface operator. Reconnect PC use after changing execution mode. Operator model changes apply to the next UI task.</p>
    <div class="settings-platform-provider-forms">
      <label class="settings-platform-field settings-platform-field-wide"><span>UI execution</span>
        <select id="settings-computer-use-mode" ${disabled ? 'disabled' : ''}>
          <option value="direct" ${state.executionMode === 'direct' ? 'selected' : ''}>Chat model directly</option>
          <option value="delegated" ${state.executionMode === 'delegated' ? 'selected' : ''}>Separate interface operator</option>
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Decision model</span>
        <select id="settings-computer-use-model" ${disabled || (state.executionMode === 'direct' && model) ? 'disabled' : ''}>
          ${!model ? `<option selected disabled value="">Unavailable: ${escapeHtml(state.modelId)}</option>` : ''}
          ${selection.providers.map((provider) => `<optgroup label="${escapeHtml(provider.label)}">${provider.models.map((option) =>
            `<option value="${escapeHtml(JSON.stringify([provider.provider_id, option.model_id]))}" ${provider.provider_id === state.providerId && option.model_id === state.modelId ? 'selected' : ''}>${escapeHtml(option.label)}</option>`
          ).join('')}</optgroup>`).join('')}
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Reasoning effort</span>
        <select id="settings-computer-use-effort" ${disabled || !model || (state.executionMode === 'direct' && validEffort) ? 'disabled' : ''}>
          ${!validEffort ? `<option selected disabled value="${escapeHtml(state.effort)}">Unavailable: ${escapeHtml(state.effort)}</option>` : ''}
          ${efforts.length ? efforts.map((option) => `<option value="${escapeHtml(option.effort)}" ${option.effort === state.effort ? 'selected' : ''}>${escapeHtml(option.label)}</option>`).join('') : '<option value="">Default</option>'}
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Recovery model</span>
        <select id="settings-computer-use-fallback" ${disabled || state.executionMode === 'direct' ? 'disabled' : ''}>
          <option value="" ${!state.fallbackModelId ? 'selected' : ''}>Return to chat</option>
          ${state.fallbackModelId && !selection.providers.flatMap(provider => provider.models).some(option => option.model_id === state.fallbackModelId)
            ? `<option selected disabled value="${escapeHtml(state.fallbackModelId)}">Unavailable: ${escapeHtml(state.fallbackModelId)}</option>` : ''}
          ${selection.providers.flatMap(provider => provider.models).filter(option => option.model_id !== state.modelId
            && option.supported_reasoning_efforts.some(effort => effort.effort === 'medium')).map(option =>
            `<option value="${escapeHtml(option.model_id)}" ${option.model_id === state.fallbackModelId ? 'selected' : ''}>${escapeHtml(option.label)} · Mid</option>`).join('')}
        </select>
      </label>
      ${!selection.available ? '<p class="settings-inline-error" role="alert">The saved model is unavailable. Choose an available model to continue PC use.</p>' : ''}
      ${state.error ? `<p class="settings-inline-error" role="alert">${escapeHtml(state.error)}</p>` : ''}
      <button type="button" id="settings-computer-use-save" ${disabled || !model || !validEffort || !changed ? 'disabled' : ''}>
        <span class="material-symbols-rounded" aria-hidden="true">${state.saving ? 'sync' : 'save'}</span>
        ${state.saving ? 'Saving' : 'Save decision model'}
      </button>
    </div>
  </section>`;
}

type ControllerContext = {
  state: ComputerUseDraft;
  getSettings: () => PlatformSettings | null;
  setSelection: (selection: ComputerUseSettings) => void;
  render: () => void;
  notify: (message: string) => void;
};

export function createComputerUseController(context: ControllerContext) {
  const { state, getSettings, render } = context;
  let requestVersion = 0;
  async function save() {
    const settings = getSettings();
    if (!settings?.computer_use?.can_configure || state.saving) return;
    const workspaceId = settings.workspace.workspace_id;
    if (workspaceId !== state.workspaceId) return;
    const generation = state.generation;
    const request = ++requestVersion;
    const current = () => state.generation === generation && request === requestVersion
      && getSettings()?.workspace.workspace_id === workspaceId;
    state.saving = true;
    state.error = '';
    const payload = { workspace_id: workspaceId, provider_id: state.providerId,
      model_id: state.modelId, reasoning_effort: state.effort || null,
      execution_mode: state.executionMode, fallback_model_id: state.fallbackModelId || null,
      fallback_reasoning_effort: state.fallbackEffort || null };
    render();
    try {
      const selection = await requestJson<ComputerUseSettings>('/api/settings/computer-use', {
        method: 'POST', body: JSON.stringify(payload),
      });
      if (!current() || selection.workspace_id !== workspaceId) return;
      context.setSelection(selection);
      syncComputerUseDraft(state, getSettings(), true);
      context.notify('PC use decision model updated.');
    } catch (error) {
      if (current()) {
        state.error = error instanceof Error ? error.message : 'Unable to update the decision model.';
      }
    } finally {
      if (current()) {
        state.saving = false;
        render();
      }
    }
  }
  function bind() {
    document.getElementById('settings-computer-use-mode')?.addEventListener('change', (event) => {
      state.executionMode = (event.currentTarget as HTMLSelectElement).value as 'direct' | 'delegated';
      if (state.executionMode === 'direct') { state.fallbackModelId = ''; state.fallbackEffort = ''; }
      state.error = ''; render();
    });
    document.getElementById('settings-computer-use-fallback')?.addEventListener('change', (event) => {
      state.fallbackModelId = (event.currentTarget as HTMLSelectElement).value;
      state.fallbackEffort = state.fallbackModelId ? 'medium' : '';
      state.error = ''; render();
    });
    document.getElementById('settings-computer-use-model')?.addEventListener('change', (event) => {
      const [providerId, modelId] = JSON.parse((event.currentTarget as HTMLSelectElement).value) as [string, string];
      state.providerId = providerId;
      state.modelId = modelId;
      if (state.fallbackModelId === modelId) { state.fallbackModelId = ''; state.fallbackEffort = ''; }
      const model = selectedModel(getSettings(), state);
      state.effort = model?.supported_reasoning_efforts.some((option) => option.effort === 'low')
        ? 'low' : model?.default_reasoning_effort || '';
      state.error = '';
      render();
    });
    document.getElementById('settings-computer-use-effort')?.addEventListener('change', (event) => {
      state.effort = (event.currentTarget as HTMLSelectElement).value;
      state.error = '';
      render();
    });
    document.getElementById('settings-computer-use-save')?.addEventListener('click', () => { void save(); });
  }
  return { bind, save };
}
