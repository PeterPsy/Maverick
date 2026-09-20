// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PlatformSettings } from './adminApi';
import type { SettingsPanelActions } from './settingsPanel';
import { bindSettingsPanelEvents, createSettingsPanelState, settingsPanelHtml } from './settingsPanel';
import { createAgenticBindingController } from './agenticBindingController';

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ''; });

function settings(enabled = false) {
  return {
    user: { username: 'admin', platform_role: 'admin' },
    workspace: { workspace_id: 'default', name: 'Default' },
    provider: { native_agents: { items: [{
      runtime_engine_id: 'antigravity-cli', label: 'Antigravity',
      selectable: enabled, provider_status: enabled ? 'active' : 'disabled',
      unavailable_reason: enabled ? null : 'native_agent_disabled',
      models: [{ model_id: 'gemini-3.8-flash-high' }]
    }] } },
    runtime: { sessions: [] }
  } as unknown as PlatformSettings;
}

function renderFlow(initial = settings()) {
  let current = initial;
  const state = createSettingsPanelState();
  const render = () => {
    document.body.innerHTML = settingsPanelHtml(current, state);
    const actions: SettingsPanelActions = {
      onActivateNativeProvider: controller.activateProvider,
      onClearAllRuntimeSessions: vi.fn(), onClearRuntimeSession: vi.fn(), onLogout: vi.fn(),
      onHostedProviderRoutingChanged: vi.fn(), onSaveAgenticBinding: vi.fn(),
      onSaveHostedProviderSettings: vi.fn(), onRefreshProviderUsage: vi.fn(),
      onSaveSpeechProviderSettings: vi.fn(), onSpeechAudioModelChanged: vi.fn(),
      onSpeechConversationModelChanged: vi.fn()
    };
    bindSettingsPanelEvents(actions);
  };
  const controller = createAgenticBindingController({
    state, render, getSettings: () => current,
    setSettings: (next) => { current = next; }
  });
  render();
  return { state, controller };
}

describe('native connection activation in Settings', () => {
  it('activates only after a click and refreshes availability from the backend', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ provider: { status: 'active' } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => settings(true) });
    vi.stubGlobal('fetch', fetch);
    const { state } = renderFlow();
    const button = document.querySelector<HTMLButtonElement>('[data-native-provider-activate]')!;
    expect(button.textContent).toContain('Enable Antigravity');
    expect(fetch).not.toHaveBeenCalled();
    button.click();
    expect(document.querySelector<HTMLButtonElement>('[data-native-provider-activate]')?.disabled).toBe(true);
    await vi.waitFor(() => expect(state.activatingNativeProviders.size).toBe(0));
    expect(fetch).toHaveBeenNthCalledWith(1, '/api/providers/native/activate', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
      body: JSON.stringify({ provider_id: 'antigravity-cli', confirmation: 'native-runtime-reviewed' })
    }));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/settings/platform', expect.any(Object));
    expect(document.querySelector('[data-native-provider-activate]')).toBeNull();
    expect(document.body.textContent).not.toContain('Native Agent Disabled');
  });

  it('keeps the action available after an activation error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, json: async () => ({ error: 'native_runtime_unavailable' })
    }));
    const { state } = renderFlow();
    document.querySelector<HTMLButtonElement>('[data-native-provider-activate]')!.click();
    await vi.waitFor(() => expect(state.activatingNativeProviders.size).toBe(0));
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('native_runtime_unavailable');
    expect(document.querySelector<HTMLButtonElement>('[data-native-provider-activate]')?.disabled).toBe(false);
  });

  it('offers no activation when there is no authenticated catalog or the user is not an admin', () => {
    const unavailable = settings();
    unavailable.provider.native_agents!.items[0].models = [];
    renderFlow(unavailable);
    expect(document.querySelector('[data-native-provider-activate]')).toBeNull();
    const member = settings();
    member.user.platform_role = 'member';
    renderFlow(member);
    expect(document.querySelector('[data-native-provider-activate]')).toBeNull();
  });
});
