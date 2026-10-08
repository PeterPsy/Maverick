import { getAppDependencies, requestJson } from './adminApi';
import { escapeAttr, escapeHtml } from './html';

type SynthesisEngine = { engine: string; label?: string; available: boolean; model?: string; detail?: string };
type SynthesisHealth = {
  synthesis: SynthesisEngine[];
  settings: { synthesis_engine: string; synthesis_language: string };
};

export type SpeechSynthesisState = {
  workspaceId: string;
  providerAppId: string;
  engines: SynthesisEngine[];
  engine: string;
  language: string;
  loading: boolean;
  saving: boolean;
  loaded: boolean;
  error: string;
};

export function createSpeechSynthesisState(): SpeechSynthesisState {
  return { workspaceId: '', providerAppId: '', engines: [], engine: '', language: 'auto', loading: false, saving: false, loaded: false, error: '' };
}

const optionalSecrets = {
  logical_names: ['openrouter-api-key', 'deepinfra-api-key', 'google-ai-studio-api-key'],
  required: false
};

export function createSpeechSynthesisController(context: {
  state: SpeechSynthesisState;
  render: () => void;
  notify: (message: string) => void;
}) {
  const state = context.state;
  let revision = 0;

  function reset() {
    revision += 1;
    Object.assign(state, createSpeechSynthesisState());
  }

  async function load(workspaceId: string, force = false) {
    if (!workspaceId) return;
    if (state.workspaceId !== workspaceId) reset();
    if (state.loading || state.saving || (state.loaded && !force)) return;
    state.workspaceId = workspaceId;
    const currentRevision = ++revision;
    state.loading = true;
    state.error = '';
    context.render();
    try {
      const dependencies = await getAppDependencies('settings');
      if (currentRevision !== revision) return;
      if (dependencies.workspace_id !== workspaceId) throw new Error('The active workspace changed. Reload voice settings.');
      const dependency = dependencies.dependencies.find((item) => item.alias === 'text-to-speech');
      const providerAppId = dependency?.selected_provider_app_ids[0] || '';
      if (!providerAppId) throw new Error('Select a text-to-speech provider for Settings in App links.');
      const health = await requestJson<SynthesisHealth>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
        method: 'POST',
        body: JSON.stringify({ action: 'engine_health', include_voices: false, _app_secret_request: optionalSecrets })
      });
      if (currentRevision !== revision) return;
      state.providerAppId = providerAppId;
      applyHealth(health);
      state.loaded = true;
    } catch (error) {
      if (currentRevision === revision) state.error = error instanceof Error ? error.message : 'Unable to load text-to-speech settings.';
    } finally {
      if (currentRevision === revision) { state.loading = false; context.render(); }
    }
  }

  function applyHealth(health: SynthesisHealth) {
    state.engines = health.synthesis;
    state.engine = health.settings.synthesis_engine;
    state.language = health.settings.synthesis_language;
  }

  async function save() {
    if (!state.providerAppId || state.saving || state.loading) return;
    const currentRevision = revision;
    state.saving = true;
    state.error = '';
    context.render();
    try {
      const result = await requestJson<{ engines: SynthesisHealth }>(`/api/apps/${encodeURIComponent(state.providerAppId)}/backend`, {
        method: 'POST',
        body: JSON.stringify({ action: 'set_engine', synthesis_engine: state.engine, synthesis_language: state.language,
          _app_secret_request: optionalSecrets })
      });
      if (currentRevision !== revision) return;
      applyHealth(result.engines);
      context.notify('Text-to-speech settings updated.');
    } catch (error) {
      if (currentRevision === revision) state.error = error instanceof Error ? error.message : 'Unable to save text-to-speech settings.';
    } finally {
      if (currentRevision === revision) { state.saving = false; context.render(); }
    }
  }

  function bind() {
    document.getElementById('settings-tts-engine')?.addEventListener('change', (event) => {
      state.engine = (event.currentTarget as HTMLSelectElement).value;
      state.error = '';
      context.render();
    });
    document.getElementById('settings-tts-language')?.addEventListener('input', (event) => {
      state.language = (event.currentTarget as HTMLInputElement).value;
    });
    document.getElementById('settings-tts-save')?.addEventListener('click', () => { void save(); });
    document.getElementById('settings-tts-retry')?.addEventListener('click', () => { void load(state.workspaceId, true); });
  }

  return { load, save, reset, bind };
}

const engineLabels: Record<string, string> = {
  auto: 'Automatic local voice', piper: 'Piper', 'espeak-ng': 'eSpeak NG', espeak: 'eSpeak',
  'kokoro-openrouter': 'Kokoro · OpenRouter', 'kokoro-deepinfra': 'Kokoro · DeepInfra', gemini: 'Gemini 3.8 Flash-Lite TTS'
};

export function speechSynthesisSettingsHtml(state: SpeechSynthesisState): string {
  const selected = state.engines.find((item) => item.engine === state.engine);
  const disabled = state.loading || state.saving;
  const engines = [{ engine: 'auto', available: true }, ...state.engines];
  return `<section class="settings-hosted-provider-group settings-tts-group" aria-labelledby="settings-tts-title">
    <div class="settings-heading"><div><p class="settings-kicker">Text to speech</p><h3 id="settings-tts-title">Read-aloud voice</h3></div></div>
    ${state.loading ? '<p class="settings-card-copy" role="status">Loading voice settings…</p>' : ''}
    ${state.loaded ? `<div class="settings-tts-controls">
      <label>Voice engine<select id="settings-tts-engine" ${disabled ? 'disabled' : ''}>
        ${engines.map((item) => `<option value="${escapeAttr(item.engine)}" ${item.engine === state.engine ? 'selected' : ''} ${!item.available && item.engine !== state.engine ? 'disabled' : ''}>${escapeHtml(engineLabels[item.engine] || item.engine)}${item.available ? '' : ' · unavailable'}</option>`).join('')}
      </select></label>
      <label>Language<input id="settings-tts-language" list="settings-tts-languages" value="${escapeAttr(state.language)}" ${disabled ? 'disabled' : ''} autocomplete="off" placeholder="auto or it-IT">
        <datalist id="settings-tts-languages"><option value="auto">Automatic</option><option value="it-IT">Italian</option><option value="en-US">English</option></datalist>
      </label>
    </div>
    ${selected && !selected.available ? `<p class="settings-platform-error">${escapeHtml(selected.detail || 'The selected voice engine is unavailable.')}</p>` : ''}
    <button type="button" class="settings-secondary" id="settings-tts-save" ${disabled || (state.engine !== 'auto' && !selected?.available) ? 'disabled' : ''}>${state.saving ? 'Saving…' : 'Save voice settings'}</button>` : ''}
    ${state.error ? `<p class="settings-platform-error" role="alert">${escapeHtml(state.error)}</p><button type="button" class="settings-secondary" id="settings-tts-retry" ${disabled ? 'disabled' : ''}>Retry</button>` : ''}
  </section>`;
}
