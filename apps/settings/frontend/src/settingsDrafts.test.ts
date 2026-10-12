import { expect, it } from 'vitest';
import { createSettingsPanelState, hostedProviderRoutingDraft, syncSettingsPanelDraft, updateHostedProviderRoutingDraft, updateSpeechAudioModel } from './settingsDrafts';
import type { PlatformSettings } from './adminApi';

function settings(workspaceId = 'default') {
  return { workspace: { workspace_id: workspaceId }, provider: {
    hosted_text: { active_provider: { default_model_family: 'speech-model', model_options: [] } },
    speech_stt: { model_settings: { audio_transcription_model_id: 'nova-3', conversation_model_id: 'flux-general-multi' } },
  } } as unknown as PlatformSettings;
}

it('preserves voice and routing edits on inventory refreshes and acknowledgements from other sections', () => {
  const state = createSettingsPanelState(); const saved = settings();
  syncSettingsPanelDraft(state, saved);
  updateSpeechAudioModel(state, 'my-audio');
  updateHostedProviderRoutingDraft(state, saved, 'speech-model', 'zdr', true);
  syncSettingsPanelDraft(state, saved);
  expect(state.speechAudioModelId).toBe('my-audio');
  expect(hostedProviderRoutingDraft(state, 'speech-model').zdr).toBe(true);
  syncSettingsPanelDraft(state, saved, { speech: true });
  expect(state.speechAudioModelId).toBe('nova-3');
  expect(hostedProviderRoutingDraft(state, 'speech-model').zdr).toBe(true);
  syncSettingsPanelDraft(state, settings('another-workspace'));
  expect(hostedProviderRoutingDraft(state, 'speech-model').zdr).toBe(false);
});
