import type { PlatformSettings, ProviderModelOption } from './adminApi';
import type { SettingsPanelState } from './settingsDrafts';
import { openHostedModelId } from './settingsDrafts';
import { hostedModelOptionsForSettings } from './providerModelOptions';
import { speechSynthesisSettingsHtml } from './speechSynthesisSettings';
import { modelSettingsHeadingHtml } from './modelsPage';
import { hostedProviderSettingsListHtml } from './speechRoutingPage';
import { speechSttSettingsListHtml } from './speechTranscriptionPage';

export function voicePageHtml(settings: PlatformSettings, state: SettingsPanelState) {
  const modelOptions = hostedModelOptionsForSettings(settings).filter(modelSupportsSpeechOutput);
  return speechModelSettingsCardHtml(modelOptions, openHostedModelId(settings, state),
    settings.provider.hosted_text?.active_provider || null, settings.provider.speech_stt || null, settings, state);
}

function speechModelSettingsCardHtml(
  hostedSpeechModelOptions: ProviderModelOption[],
  openHostedModel: string,
  hostedProvider: PlatformSettings['provider']['active_provider'] | null,
  speechStt: PlatformSettings['provider']['speech_stt'] | null,
  settings: PlatformSettings,
  state: SettingsPanelState
) {
  return `<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${modelSettingsHeadingHtml('record_voice_over', 'Speech model settings')}
    <div class="settings-platform-provider-forms">
      ${speechSynthesisSettingsHtml(state.speechSynthesis)}
      ${hostedProviderSettingsListHtml({
        modelOptions: hostedSpeechModelOptions,
        openHostedModel,
        hostedProvider,
        settings,
        state,
        emptyMessage: 'No hosted speech models are available from the active hosted providers.',
        inactiveMessage: 'Activate the hosted provider before saving speech model routing.'
      })}
      ${speechSttSettingsListHtml(speechStt, state)}
    </div>
  </section>`;
}

function modelSupportsSpeechOutput(option: ProviderModelOption): boolean {
  return (option.output_modalities || []).includes('speech');
}

