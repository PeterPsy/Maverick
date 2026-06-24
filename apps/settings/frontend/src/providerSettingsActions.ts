import {
  configureActiveProvider,
  configureHostedProvider,
  configureSpeechProvider,
  getPlatformSettings,
  type PlatformSettings
} from './adminApi';
import { hostedProviderRoutingDraft, syncSettingsPanelDraft, type SettingsPanelState } from './settingsPanel';

type SettingsNotice = {
  message: string;
  tone: 'error' | 'info' | 'success';
};

type ProviderSettingsActionContext = {
  render: () => void;
  setNotice: (notice: SettingsNotice) => void;
  setSettings: (settings: PlatformSettings) => void;
  settings: PlatformSettings | null;
  state: SettingsPanelState;
};

export async function saveActiveProviderSettings(context: ProviderSettingsActionContext) {
  const providerId = context.settings?.provider.active_provider?.provider_id;
  if (!providerId || !context.state.draftModelId) {
    context.state.providerError = 'Provider not loaded.';
    context.render();
    return;
  }
  context.state.isSavingProvider = true;
  context.state.providerError = '';
  context.render();
  try {
    await configureActiveProvider({
      provider_id: providerId,
      model_id: context.state.draftModelId,
      model_reasoning_effort: context.state.draftReasoningEffort || null
    });
    const settings = await getPlatformSettings();
    context.setSettings(settings);
    syncSettingsPanelDraft(context.state, settings);
    context.setNotice({ tone: 'success', message: 'Provider settings updated.' });
  } catch (error) {
    context.state.providerError = error instanceof Error ? error.message : 'Unable to update provider settings.';
  } finally {
    context.state.isSavingProvider = false;
    context.render();
  }
}

export async function saveHostedProviderSettings(context: ProviderSettingsActionContext) {
  const providerId = context.settings?.provider.hosted_text?.active_provider?.provider_id;
  if (!providerId || !context.state.hostedDraftModelId) {
    context.state.hostedProviderErrorModelId = context.state.hostedDraftModelId;
    context.state.hostedProviderError = 'Hosted provider not loaded.';
    context.render();
    return;
  }
  context.state.isSavingHostedProvider = true;
  context.state.hostedProviderError = '';
  context.state.hostedProviderErrorModelId = context.state.hostedDraftModelId;
  context.render();
  try {
    await configureHostedProvider({
      provider_id: providerId,
      model_id: context.state.hostedDraftModelId,
      openrouter_provider_routing: hostedProviderRoutingDraft(context.state, context.state.hostedDraftModelId)
    });
    const settings = await getPlatformSettings();
    context.setSettings(settings);
    syncSettingsPanelDraft(context.state, settings);
    context.setNotice({ tone: 'success', message: 'Hosted model settings updated.' });
  } catch (error) {
    context.state.hostedProviderErrorModelId = context.state.hostedDraftModelId;
    context.state.hostedProviderError = error instanceof Error ? error.message : 'Unable to update hosted model settings.';
  } finally {
    context.state.isSavingHostedProvider = false;
    context.render();
  }
}

export async function saveSpeechProviderSettings(context: ProviderSettingsActionContext) {
  const providerId = context.settings?.provider.speech_stt?.active_provider?.provider_id;
  if (!providerId || !context.state.speechAudioModelId || !context.state.speechConversationModelId) {
    context.state.speechProviderError = 'Speech provider not loaded.';
    context.render();
    return;
  }
  context.state.isSavingSpeechProvider = true;
  context.state.speechProviderError = '';
  context.render();
  try {
    await configureSpeechProvider({
      provider_id: providerId,
      audio_transcription_model_id: context.state.speechAudioModelId,
      conversation_model_id: context.state.speechConversationModelId
    });
    const settings = await getPlatformSettings();
    context.setSettings(settings);
    syncSettingsPanelDraft(context.state, settings);
    context.setNotice({ tone: 'success', message: 'Speech model settings updated.' });
  } catch (error) {
    context.state.speechProviderError = error instanceof Error ? error.message : 'Unable to update speech model settings.';
  } finally {
    context.state.isSavingSpeechProvider = false;
    context.render();
  }
}
