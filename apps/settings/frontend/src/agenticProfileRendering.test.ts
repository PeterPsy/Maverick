// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgenticAdminItem } from './adminApi';
import { createAgenticBindingController } from './agenticBindingController';
import { binding, freezeDeep, profile, settings } from './agenticProfileTestFixtures';
import { bindSettingsPanelEvents, createSettingsPanelState, settingsPanelHtml, type SettingsPanelActions } from './settingsPanel';

const api = vi.hoisted(() => ({ save: vi.fn(), get: vi.fn() }));
vi.mock('./adminApi', () => ({ configureAgenticWorkspaceBinding: api.save, getPlatformSettings: api.get }));

function enabled(revision: string, isDefault = false): AgenticAdminItem {
  return profile(revision, {
    binding: { ...binding(true, isDefault), binding_id: `binding-${revision}` },
    selectable: true, enable_eligible: true, full_workspace_status: 'certified',
    blocked_reason: null, enable_blocked_reason: null,
  });
}

function actions(): SettingsPanelActions {
  return {
    onClearAllRuntimeSessions: vi.fn(), onClearRuntimeSession: vi.fn(), onLogout: vi.fn(),
    onHostedProviderRoutingChanged: vi.fn(), onSaveAgenticBinding: vi.fn(),
    onSaveHostedProviderSettings: vi.fn(), onRefreshProviderUsage: vi.fn(),
    onSaveSpeechProviderSettings: vi.fn(), onSpeechAudioModelChanged: vi.fn(),
    onSpeechConversationModelChanged: vi.fn(),
  };
}

function card(revision: string): HTMLDetailsElement {
  return document.querySelector<HTMLDetailsElement>(`[data-settings-model-accordion="agentic-codex:sol:${revision}"]`)!;
}

describe('Settings revision grouping rendering and exact binding controls', () => {
  beforeEach(() => {
    api.save.mockReset().mockResolvedValue({});
    api.get.mockReset();
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('No network in rendering tests'); }));
    document.body.innerHTML = '';
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it('shows the enabled pin and exact identity, with other enabled revisions in closed history', () => {
    const payload = freezeDeep(settings([profile('15'), enabled('12'), enabled('14', true)]));
    const before = JSON.stringify(payload);
    document.body.innerHTML = settingsPanelHtml(payload, createSettingsPanelState());
    bindSettingsPanelEvents(actions());
    const group = document.querySelector('[data-agentic-profile-group]')!;
    expect(group.querySelector(':scope > details > summary')?.textContent).toContain('codex:sol@14');
    const history = group.querySelector<HTMLDetailsElement>('[data-agentic-revision-history]')!;
    expect(history.open).toBe(false);
    expect(history.querySelector(':scope > summary')?.textContent).toContain('Other revisions · 2');
    expect(history.querySelector(':scope > summary')?.textContent).toContain('1 enabled');
    expect(history.contains(card('12'))).toBe(true);
    expect(history.contains(card('15'))).toBe(true);
    expect(JSON.stringify(payload)).toBe(before);
    expect(api.save).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('opening a historical card does not close its own history container', () => {
    document.body.innerHTML = settingsPanelHtml(settings([enabled('14'), profile('15')]), createSettingsPanelState());
    bindSettingsPanelEvents(actions());
    const history = document.querySelector<HTMLDetailsElement>('[data-agentic-revision-history]')!;
    expect(history.hasAttribute('data-settings-model-accordion')).toBe(false);
    card('14').open = true;
    history.open = true;
    history.dispatchEvent(new Event('toggle'));
    card('15').open = true;
    card('15').dispatchEvent(new Event('toggle'));
    expect(history.open).toBe(true);
    expect(card('15').open).toBe(true);
    expect(card('14').open).toBe(false);
    expect(api.save).not.toHaveBeenCalled();
  });

  it('a historical uncertified candidate cannot inherit the primary eligibility or binding', () => {
    const handlers = actions();
    document.body.innerHTML = settingsPanelHtml(settings([enabled('14'), profile('15')]), createSettingsPanelState());
    bindSettingsPanelEvents(handlers);
    const candidate = card('15');
    expect(candidate.querySelector('summary')?.textContent).toContain('codex:sol@15');
    const toggle = candidate.querySelector<HTMLInputElement>('[data-agentic-model-toggle]')!;
    expect(toggle.disabled).toBe(true);
    expect(toggle.checked).toBe(false);
    toggle.click();
    expect(handlers.onSaveAgenticBinding).not.toHaveBeenCalled();
    expect(candidate.querySelector('[data-agentic-binding-save]')?.textContent).toContain('Create binding');
  });

  it('historical save uses that original revision, binding id, CAS and policy through the existing controller', async () => {
    const historic = enabled('12');
    historic.binding!.revision = 42;
    historic.binding!.workspace_policy_ceiling.max_estimated_cost_microusd = 70_000;
    historic.binding!.actor_policy.allowed_user_ids = ['historic-actor'];
    const payload = freezeDeep(settings([enabled('14', true), historic]));
    api.get.mockResolvedValue(payload);
    const state = createSettingsPanelState();
    document.body.innerHTML = settingsPanelHtml(payload, state);
    const controller = createAgenticBindingController({ getSettings: () => payload, render: vi.fn(), setSettings: vi.fn(), state });
    bindSettingsPanelEvents({ ...actions(), onSaveAgenticBinding: controller.save });
    card('12').querySelector<HTMLButtonElement>('[data-agentic-binding-save]')!.click();
    await vi.waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    expect(api.save).toHaveBeenCalledWith(expect.objectContaining({
      definition_id: 'codex:sol', definition_revision: '12', binding_id: 'binding-12',
      expected_revision: 42, enabled: true, is_default: false,
      actor_policy: expect.objectContaining({ allowed_user_ids: ['historic-actor'] }),
      policy_patch: expect.objectContaining({ max_estimated_cost_microusd: 70_000 }),
    }));
    await vi.waitFor(() => expect(state.savingAgenticBindings.size).toBe(0));
    expect(historic.binding!.revision).toBe(42);
    expect(fetch).not.toHaveBeenCalled();
  });
});
