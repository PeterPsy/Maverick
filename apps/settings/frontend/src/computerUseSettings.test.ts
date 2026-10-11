// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ComputerUseSettings, PlatformSettings } from './adminApi';
import { computerUseSettingsHtml, createComputerUseController, createComputerUseDraft, syncComputerUseDraft } from './computerUseSettings';

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ''; });

const selection = (overrides: Partial<ComputerUseSettings> = {}): ComputerUseSettings => ({
  workspace_id: 'default', provider_id: 'codex', model_id: 'gpt-6-luna', reasoning_effort: 'low',
  available: true, unavailable_reason: null, can_configure: true,
  providers: [{ provider_id: 'codex', label: 'Codex', models: ['gpt-6-luna', 'gpt-6-sol'].map((model_id) => ({
    model_id, label: model_id, description: null, default_reasoning_effort: 'medium',
    supported_reasoning_efforts: [{ effort: 'low', label: 'Low', description: null },
      { effort: 'medium', label: 'Medium', description: null }],
  })) }], ...overrides,
});

function setup(initial = selection()) {
  let settings = { workspace: { workspace_id: 'default' }, computer_use: initial } as PlatformSettings;
  const state = createComputerUseDraft();
  const notify = vi.fn();
  syncComputerUseDraft(state, settings);
  const render = () => { document.body.innerHTML = computerUseSettingsHtml(settings, state); controller.bind(); };
  const controller = createComputerUseController({ state, getSettings: () => settings,
    setSelection: (computer_use) => { settings = { ...settings, computer_use }; }, render, notify });
  render();
  return { state, controller, notify, render, getSettings: () => settings,
    switchWorkspace: (workspace_id = 'other') => {
      settings = { ...settings, workspace: { ...settings.workspace, workspace_id },
        computer_use: selection({ workspace_id }) };
      syncComputerUseDraft(state, settings);
      render();
    } };
}

describe('PC use decision model settings', () => {
  it('clears recovery when switching to direct UI execution', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => selection({ execution_mode: 'direct' }) });
    vi.stubGlobal('fetch', fetch);
    const { state, controller } = setup(selection({ fallback_model_id: 'gpt-6-sol', fallback_reasoning_effort: 'medium' }));
    const mode = document.getElementById('settings-computer-use-mode') as HTMLSelectElement;
    mode.value = 'direct'; mode.dispatchEvent(new Event('change'));
    expect(state.fallbackModelId).toBe('');
    expect((document.getElementById('settings-computer-use-model') as HTMLSelectElement).disabled).toBe(true);
    await controller.save();
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ execution_mode: 'direct', fallback_model_id: null, fallback_reasoning_effort: null });
  });

  it('saves a distinct recovery model at medium effort', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => selection({ fallback_model_id: 'gpt-6-sol', fallback_reasoning_effort: 'medium' }) });
    vi.stubGlobal('fetch', fetch);
    const { controller, state } = setup();
    const recovery = document.getElementById('settings-computer-use-fallback') as HTMLSelectElement;
    expect([...recovery.options].map(option => option.value)).toEqual(['', 'gpt-6-sol']);
    recovery.value = 'gpt-6-sol'; recovery.dispatchEvent(new Event('change'));
    await controller.save();
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ fallback_model_id: 'gpt-6-sol', fallback_reasoning_effort: 'medium' });
    expect(state.fallbackEffort).toBe('medium');
  });

  it('allows repairing an unavailable saved operator before saving direct mode', () => {
    const { state, render } = setup(selection({ available: false, model_id: 'removed' }));
    state.executionMode = 'direct'; render();
    expect((document.getElementById('settings-computer-use-model') as HTMLSelectElement).disabled).toBe(false);
  });

  it('shows Luna low as the saved model and disables an unchanged save', () => {
    const { state } = setup();
    expect(state.modelId).toBe('gpt-6-luna');
    expect((document.getElementById('settings-computer-use-effort') as HTMLSelectElement).value).toBe('low');
    expect((document.getElementById('settings-computer-use-save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('saves the chosen model and effort through the dedicated workspace endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => selection({ model_id: 'gpt-6-sol', reasoning_effort: 'medium' }) });
    vi.stubGlobal('fetch', fetch);
    const { controller, state, notify } = setup();
    const model = document.getElementById('settings-computer-use-model') as HTMLSelectElement;
    model.value = JSON.stringify(['codex', 'gpt-6-sol']);
    model.dispatchEvent(new Event('change'));
    expect(state.effort).toBe('low');
    const effort = document.getElementById('settings-computer-use-effort') as HTMLSelectElement;
    effort.value = 'medium'; effort.dispatchEvent(new Event('change'));
    await controller.save();
    expect(fetch.mock.calls[0][0]).toBe('/api/settings/computer-use');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ workspace_id: 'default', provider_id: 'codex',
      model_id: 'gpt-6-sol', reasoning_effort: 'medium', execution_mode: 'delegated',
      fallback_model_id: null, fallback_reasoning_effort: null });
    expect(state.saving).toBe(false);
    expect(state.modelId).toBe('gpt-6-sol');
    expect(notify).toHaveBeenCalledWith('PC use decision model updated.');
    expect((document.getElementById('settings-computer-use-save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps the draft and displays an escaped error after a rejected save', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 400,
      json: async () => ({ error: '<invalid model>' }) }));
    const { controller, state, getSettings } = setup();
    state.effort = 'medium';
    await controller.save();
    expect(getSettings().computer_use?.reasoning_effort).toBe('low');
    expect(state.effort).toBe('medium');
    expect(document.querySelector('[role="alert"]')?.textContent).toBe('<invalid model>');
    expect(document.querySelector('invalid')).toBeNull();
  });

  it('prevents member writes and shows an unavailable saved model without changing it', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    const { controller, state } = setup(selection({ can_configure: false, available: false, model_id: 'removed' }));
    await controller.save();
    expect(fetch).not.toHaveBeenCalled();
    expect(state.modelId).toBe('removed');
    expect((document.getElementById('settings-computer-use-model') as HTMLSelectElement).disabled).toBe(true);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('saved model is unavailable');
  });

  it('ignores responses from the previous workspace and prevents duplicate submissions', async () => {
    let resolve!: (value: unknown) => void;
    const pending = new Promise((done) => { resolve = done; });
    const fetch = vi.fn().mockReturnValue(pending); vi.stubGlobal('fetch', fetch);
    const { controller, state, switchWorkspace, notify } = setup();
    state.effort = 'medium';
    const saving = controller.save();
    await controller.save();
    expect(fetch).toHaveBeenCalledTimes(1);
    switchWorkspace();
    resolve({ ok: true, json: async () => selection({ reasoning_effort: 'medium' }) });
    await saving;
    expect(state.workspaceId).toBe('other');
    expect(state.effort).toBe('low');
    expect(notify).not.toHaveBeenCalled();
  });

  it.each([false, true])('fences old saves after returning to the same workspace (new response first: %s)', async (newFirst) => {
    const responses: Array<(value: unknown) => void> = [];
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => responses.push(resolve))));
    const { controller, state, switchWorkspace, getSettings, notify } = setup();
    state.effort = 'medium';
    const oldSave = controller.save();
    switchWorkspace();
    switchWorkspace('default');
    state.modelId = 'gpt-6-sol';
    const newSave = controller.save();
    if (!newFirst) {
      responses[0]({ ok: true, json: async () => selection({ reasoning_effort: 'medium' }) });
      await oldSave;
      expect(state.saving).toBe(true);
      expect(state.modelId).toBe('gpt-6-sol');
      expect(notify).not.toHaveBeenCalled();
    }
    responses[1]({ ok: true, json: async () => selection({ model_id: 'gpt-6-sol' }) });
    await newSave;
    if (newFirst) {
      responses[0]({ ok: true, json: async () => selection({ reasoning_effort: 'medium' }) });
      await oldSave;
    }
    expect(getSettings().computer_use?.model_id).toBe('gpt-6-sol');
    expect(state.modelId).toBe('gpt-6-sol');
    expect(state.saving).toBe(false);
  });

  it('preserves unsaved edits when unrelated runtime inventory refreshes', () => {
    const { state, getSettings } = setup();
    state.effort = 'medium';
    syncComputerUseDraft(state, getSettings());
    expect(state.effort).toBe('medium');
  });
});
