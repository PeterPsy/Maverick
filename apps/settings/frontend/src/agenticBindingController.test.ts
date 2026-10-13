// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest';
import { configureAgenticWorkspaceBinding, getPlatformSettings, type PlatformSettings } from './adminApi';
import { createAgenticBindingController } from './agenticBindingController';
import { beginSettingsBindings, bindControl } from './controlBindings';
import { createSettingsPanelState } from './settingsDrafts';
import { clearSettingsDomCache, patchSettingsDom, rememberSettingsDrafts } from './settingsDom';
import { settingsPanelHtml } from './settingsPanel';

vi.mock('./adminApi', () => ({ activateNativeProvider: vi.fn(), configureAgenticWorkspaceBinding: vi.fn(), getPlatformSettings: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks(); clearSettingsDomCache();
  document.body.innerHTML = '<div id="app"></div>';
  rememberSettingsDrafts(document.getElementById('app')!);
});

function settings(enabled = false): PlatformSettings {
  const policy = { max_estimated_cost_microusd: null, require_confirmation_for_mutating: false, require_confirmation_for_destructive: true };
  return {
    workspace: { workspace_id: 'default' }, user: { platform_role: 'admin' }, provider: {},
    agentic_admin: { workspace_id: 'default', release_decision: 'GO', items: [{
      definition_id: 'model', display_name: 'Model', runtime_engine_id: 'codex', model_id: 'model',
      execution_family: 'native_agent', runtime_status: 'complete', enable_eligible: true,
      containment_status: 'GO', profile_policy_ceiling: policy, credential_bindings: [],
      binding: { binding_id: 'binding', enabled, is_default: false, workspace_policy_ceiling: policy,
        actor_policy: { allow_workspace_admins: true, allowed_user_ids: [], allowed_workspace_role_ids: ['member'], allowed_agent_type_ids: [] } }
    }] }
  } as unknown as PlatformSettings;
}

function mount(initial = settings()) {
  let current = initial;
  let saving: Promise<void>;
  const state = createSettingsPanelState();
  const render = () => {
    patchSettingsDom(document.getElementById('app')!, settingsPanelHtml(current, state));
    beginSettingsBindings();
    const toggle = document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!;
    bindControl(toggle, 'change', () => { saving = controller.save('model', { enabled: toggle.checked }); });
  };
  const controller = createAgenticBindingController({ state, render, getSettings: () => current, setSettings: next => { current = next; } });
  render();
  return { controller, state, render, saving: () => saving! };
}

it('shows one enabled Gemini 4 Argon model for its Antigravity effort aliases', () => {
  const initial = settings(true);
  const template = initial.agentic_admin!.items[0];
  initial.agentic_admin!.items = ['low', 'medium', 'high'].map(effort => ({
    ...template,
    definition_id: `argon-${effort}`,
    display_name: `Antigravity · gemini-4-argon-${effort}`,
    runtime_engine_id: 'antigravity-cli',
    model_id: `gemini-4-argon-${effort}`,
    default_reasoning_effort: effort,
    selectable: true,
  }));
  document.body.innerHTML = settingsPanelHtml(initial, createSettingsPanelState());

  const toggles = document.querySelectorAll<HTMLInputElement>('[data-agentic-model-toggle]');
  expect(toggles).toHaveLength(1);
  expect(toggles[0].dataset.agenticDefinitionId).toBe('argon-high');
  expect(toggles[0].disabled).toBe(false);
  expect(toggles[0].checked).toBe(true);
  expect(document.body.textContent).toContain('gemini-4-argon-high');
  expect(document.body.textContent).not.toContain('Unavailable');
});

it('shows an optimistic switch and rolls back checked state and label after rejection', async () => {
  let reject!: (error: Error) => void;
  vi.mocked(configureAgenticWorkspaceBinding).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  const flow = mount();
  const draft = document.querySelector<HTMLInputElement>('[data-agentic-field=is_default]')!;
  draft.checked = true; draft.dispatchEvent(new Event('change', { bubbles: true }));
  const toggle = document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!;
  toggle.click(); flow.render();
  expect(toggle.checked).toBe(true); expect(toggle.disabled).toBe(true);
  expect(toggle.closest('label')!.textContent).toContain('On');
  await flow.controller.save('model', { enabled: true });
  expect(configureAgenticWorkspaceBinding).toHaveBeenCalledOnce();
  reject(new Error('Rejected')); await flow.saving();
  expect(toggle.checked).toBe(false); expect(toggle.disabled).toBe(false);
  expect(toggle.closest('label')!.textContent).toContain('Off');
  expect(document.querySelector('[role=alert]')!.textContent).toContain('Rejected');
  expect(draft.checked).toBe(true);
});

it('uses the acknowledged server switch state after a successful save', async () => {
  vi.mocked(configureAgenticWorkspaceBinding).mockResolvedValue({ binding_id: 'binding', agentic_admin: settings(true).agentic_admin! });
  vi.mocked(getPlatformSettings).mockResolvedValue(settings(true));
  const flow = mount();
  document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!.click();
  await flow.saving();
  const toggle = document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!;
  expect(toggle.checked).toBe(true); expect(toggle.disabled).toBe(false);
  expect(flow.state.pendingAgenticEnabled).toEqual({});
});

it.each([true, false])('keeps the acknowledged enabled=%s state when catalog refresh is unavailable', async enabled => {
  vi.mocked(configureAgenticWorkspaceBinding).mockResolvedValue({
    binding_id: 'binding', agentic_admin: settings(enabled).agentic_admin!
  });
  vi.mocked(getPlatformSettings).mockRejectedValue(new Error('Catalog refresh unavailable'));
  const flow = mount(settings(!enabled));
  document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!.click();
  await flow.saving();
  const toggle = document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!;
  expect(toggle.checked).toBe(enabled);
  expect(toggle.disabled).toBe(false);
  expect(toggle.closest('label')!.textContent).toContain(enabled ? 'On' : 'Off');
  expect(flow.state.agenticBindingErrors.model).toBe('');
  expect(flow.state.pendingAgenticEnabled).toEqual({});
  expect(getPlatformSettings).not.toHaveBeenCalled();
});

it('ignores a late model save after the workspace state has reset', async () => {
  let finish!: (value: Awaited<ReturnType<typeof configureAgenticWorkspaceBinding>>) => void;
  vi.mocked(configureAgenticWorkspaceBinding).mockReturnValue(new Promise(done => { finish = done; }));
  vi.mocked(getPlatformSettings).mockResolvedValue(settings(true));
  const flow = mount();
  document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!.click();
  flow.controller.reset(); clearSettingsDomCache(); flow.render();
  finish({ binding_id: 'binding', agentic_admin: settings(true).agentic_admin! }); await flow.saving();
  expect(document.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!.checked).toBe(false);
  expect(flow.state.savingAgenticBindings.size).toBe(0);
});
