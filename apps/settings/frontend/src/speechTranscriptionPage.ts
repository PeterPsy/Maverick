import type { PlatformSettings, ProviderModelOption } from './adminApi';
import { speechModelOptions, type SettingsPanelState } from './settingsDrafts';
import { escapeHtml, escapeAttr } from './html';

export function speechSttSettingsListHtml(status: PlatformSettings['provider']['speech_stt'] | null, state: SettingsPanelState) {
  const provider = status?.active_provider || status?.available_providers?.find((item) => item.provider_id === 'deepgram') || null;
  const audioOptions = speechModelOptions(status, provider, 'prerecorded_transcription');
  const conversationOptions = speechModelOptions(status, provider, 'conversational_streaming');
  const selectedAudioModelId = status?.model_settings?.audio_transcription_model_id || audioOptions[0]?.model_id || 'nova-3';
  const selectedConversationModelId = status?.model_settings?.conversation_model_id || conversationOptions[0]?.model_id || 'flux-general-multi';
  const audioDraft = state.speechAudioModelId || selectedAudioModelId;
  const conversationDraft = state.speechConversationModelId || selectedConversationModelId;
  const audioOption = audioOptions.find((option) => option.model_id === audioDraft) || audioOptions[0] || null;
  const conversationOption = conversationOptions.find((option) => option.model_id === conversationDraft) || conversationOptions[0] || null;
  const audioEndpoint = speechModelEndpoint(audioOption, status?.model_settings?.endpoints?.audio_transcription || `https://api.deepgram.com/v1/listen?model=${audioDraft || 'nova-3'}`);
  const conversationEndpoint = speechModelEndpoint(conversationOption, status?.model_settings?.endpoints?.conversation || `wss://api.deepgram.com/v2/listen?model=${conversationDraft || 'flux-general-multi'}`);
  const active = Boolean(status?.active_provider && status?.credential_binding);
  const canSave = Boolean(
    active &&
      audioDraft &&
      conversationDraft &&
      !state.isSavingSpeechProvider &&
      (audioDraft !== selectedAudioModelId || conversationDraft !== selectedConversationModelId)
  );
  const providerLabel = provider?.label || provider?.provider_id || 'Deepgram';
  const providerId = provider?.provider_id || 'deepgram';
  const providerStatus = active ? 'Active provider' : 'Inactive provider';
  return `<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${escapeAttr(providerId)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${escapeHtml(providerLabel)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${escapeHtml(providerStatus)}</span>
      </div>
      ${speechModelSelectHtml({
        id: 'settings-speech-audio-model',
        label: 'Audio transcription model',
        icon: 'hearing',
        value: audioDraft,
        options: audioOptions,
        endpoint: audioEndpoint,
        description: audioOption?.description || 'Deepgram model for prerecorded audio, files, and one-shot microphone transcription.',
        disabled: !active || state.isSavingSpeechProvider,
        canSave,
        isSaving: state.isSavingSpeechProvider
      })}
      ${speechModelSelectHtml({
        id: 'settings-speech-conversation-model',
        label: 'Conversation model',
        icon: 'forum',
        value: conversationDraft,
        options: conversationOptions,
        endpoint: conversationEndpoint,
        description: conversationOption?.description || 'Deepgram Flux model for realtime voice conversation and turn detection.',
        disabled: !active || state.isSavingSpeechProvider,
        canSave,
        isSaving: state.isSavingSpeechProvider
      })}
    </section>
    ${state.speechProviderError ? `<p class="settings-platform-error">${escapeHtml(state.speechProviderError)}</p>` : ''}
    ${active ? '' : '<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`;
}

function speechModelSelectHtml({
  id,
  label,
  icon,
  value,
  options,
  endpoint,
  description,
  disabled,
  canSave,
  isSaving
}: {
  id: string;
  label: string;
  icon: string;
  value: string;
  options: ProviderModelOption[];
  endpoint: string;
  description: string;
  disabled: boolean;
  canSave: boolean;
  isSaving: boolean;
}) {
  if (!options.length) {
    return `<p class="settings-card-copy settings-platform-note">No ${escapeHtml(label.toLowerCase())} options are available.</p>`;
  }
  return `<details class="settings-model-accordion settings-speech-model-accordion">
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(icon)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${escapeHtml(label)}</span>
        </span>
        <strong>${escapeHtml(options.find((option) => option.model_id === value)?.label || value)}</strong>
        <small>${escapeHtml(value)} · ${escapeHtml(endpoint)}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${escapeHtml(label)}</span>
        <select id="${escapeAttr(id)}" ${disabled ? 'disabled' : ''}>
          ${options.map((option) => `<option value="${escapeAttr(option.model_id)}" ${option.model_id === value ? 'selected' : ''}>${escapeHtml(option.label || option.model_id)}</option>`).join('')}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${escapeHtml(endpoint)}</code>
      </div>
      <p class="settings-card-copy">${escapeHtml(description)}</p>
      <button type="button" data-speech-discard class="settings-secondary" ${canSave && !isSaving ? '' : 'disabled'}>Discard edits</button>
      <button type="button" data-speech-save="${escapeAttr(id)}" ${canSave ? '' : 'disabled'}>
        <span class="material-symbols-rounded" aria-hidden="true">${isSaving ? 'sync' : 'save'}</span>
        ${isSaving ? 'Saving' : 'Save speech model'}
      </button>
    </div>
  </details>`;
}

function speechModelEndpoint(option: ProviderModelOption | null, fallback: string) {
  const endpoint = option?.metadata?.endpoint;
  return typeof endpoint === 'string' && endpoint ? endpoint : fallback;
}

