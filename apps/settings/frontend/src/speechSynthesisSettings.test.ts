// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSpeechSynthesisController, createSpeechSynthesisState, speechSynthesisSettingsHtml } from './speechSynthesisSettings';

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ''; });

const health = {
  synthesis: [{ engine: 'gemini', available: true }, { engine: 'kokoro-openrouter', available: true }, { engine: 'kokoro-deepinfra', available: false }],
  settings: { synthesis_engine: 'gemini', synthesis_language: 'it-it' }
};
const dependencies = {
  workspace_id: 'default', dependencies: [{ alias: 'text-to-speech', selected_provider_app_ids: ['speech'] }]
};
const response = (payload: unknown) => ({ ok: true, json: async () => payload });

describe('workspace text-to-speech settings', () => {
  it('loads the selected provider and saves engine/language without changing transcription', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(dependencies)).mockResolvedValueOnce(response(health))
      .mockResolvedValueOnce(response({ engines: { ...health, settings: { synthesis_engine: 'kokoro-openrouter', synthesis_language: 'en-us' } } }));
    vi.stubGlobal('fetch', fetch);
    const state = createSpeechSynthesisState();
    const notify = vi.fn();
    const render = () => { document.body.innerHTML = speechSynthesisSettingsHtml(state); controller.bind(); };
    const controller = createSpeechSynthesisController({ state, render, notify });
    await controller.load('default');
    expect((document.getElementById('settings-tts-engine') as HTMLSelectElement).value).toBe('gemini');
    expect((document.querySelector('option[value="kokoro-deepinfra"]') as HTMLOptionElement).disabled).toBe(true);
    const engine = document.getElementById('settings-tts-engine') as HTMLSelectElement;
    engine.value = 'kokoro-openrouter';
    engine.dispatchEvent(new Event('change'));
    const language = document.getElementById('settings-tts-language') as HTMLInputElement;
    language.value = 'en-US';
    language.dispatchEvent(new Event('input'));
    await controller.save();
    expect(fetch.mock.calls[2][0]).toBe('/api/apps/speech/backend');
    const body = JSON.parse(fetch.mock.calls[2][1].body);
    expect(body).toEqual({ action: 'set_engine', synthesis_engine: 'kokoro-openrouter', synthesis_language: 'en-US',
      _app_secret_request: { logical_names: ['openrouter-api-key', 'deepinfra-api-key', 'google-ai-studio-api-key'], required: false } });
    expect(state.language).toBe('en-us');
    expect(notify).toHaveBeenCalledWith('Text-to-speech settings updated.');
  });

  it('does not apply an old workspace response after switching workspaces', async () => {
    let resolveHealth!: (value: unknown) => void;
    const pending = new Promise((resolve) => { resolveHealth = resolve; });
    const fetch = vi.fn().mockResolvedValueOnce(response(dependencies)).mockReturnValueOnce(pending);
    vi.stubGlobal('fetch', fetch);
    const state = createSpeechSynthesisState();
    const controller = createSpeechSynthesisController({ state, render: vi.fn(), notify: vi.fn() });
    const loading = controller.load('default');
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    controller.reset();
    resolveHealth(response(health));
    await loading;
    expect(state.workspaceId).toBe('');
    expect(state.loaded).toBe(false);
    expect(state.engine).toBe('');
  });

  it('reports a missing dependency and escapes provider errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ workspace_id: 'default', dependencies: [] })));
    const state = createSpeechSynthesisState();
    const controller = createSpeechSynthesisController({ state, render: vi.fn(), notify: vi.fn() });
    await controller.load('default');
    expect(state.error).toContain('App links');
    state.error = '<script>bad</script>';
    expect(speechSynthesisSettingsHtml(state)).toContain('&lt;script&gt;');
    expect(speechSynthesisSettingsHtml(state)).not.toContain('<script>');
  });
});
