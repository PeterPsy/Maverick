import { clearSettingsDrafts } from './settingsDom';
import {
  configureHostedProvider,
  configureSpeechProvider,
  type PlatformSettings
} from './adminApi';
import { hostedProviderRoutingDraft, syncSettingsPanelDraft, type SettingsPanelState } from './settingsDrafts';

type SettingsNotice = {
  message: string;
  tone: 'error' | 'info' | 'success';
};

type ProviderSettingsActionContext = {
  render: () => void;
  setNotice: (notice: SettingsNotice) => void;
  setSettings: (settings: PlatformSettings) => void;
  settings: PlatformSettings | null;
  getSettings: () => PlatformSettings | null;
  state: SettingsPanelState;
};

export async function saveHostedProviderSettings(context: ProviderSettingsActionContext) {
  const workspaceId = context.settings?.workspace.workspace_id;
  const savedModelId = context.state.hostedDraftModelId;
  const providerId = hostedProviderIdForModel(context.settings, context.state.hostedDraftModelId);
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
    const provider = await configureHostedProvider({
      provider_id: providerId,
      model_id: context.state.hostedDraftModelId,
      openrouter_provider_routing: hostedProviderRoutingDraft(context.state, context.state.hostedDraftModelId)
    });
    if (context.getSettings()?.workspace.workspace_id !== workspaceId || !context.settings) return;
    const settings = { ...context.getSettings()!, provider };
    context.setSettings(settings);
    syncSettingsPanelDraft(context.state, settings, { hostedModelId: savedModelId });
    document.querySelectorAll<HTMLElement>('[data-hosted-model-accordion]').forEach(element => { if (element.dataset.hostedModelAccordion === savedModelId) clearSettingsDrafts(element); });
    context.setNotice({ tone: 'success', message: 'Hosted model settings updated.' });
  } catch (error) {
    context.state.hostedProviderErrorModelId = context.state.hostedDraftModelId;
    context.state.hostedProviderError = error instanceof Error ? error.message : 'Unable to update hosted model settings.';
  } finally {
    context.state.isSavingHostedProvider = false;
    context.render();
  }
}

function hostedProviderIdForModel(settings: PlatformSettings | null, modelId: string): string {
  const status = settings?.provider.hosted_text || null;
  const providers = [
    status?.active_provider,
    ...(status?.available_providers || []),
  ].filter(Boolean);
  const matchedProvider = providers.find((provider) => {
    if (!provider || provider.status !== 'active') {
      return false;
    }
    return (provider.model_options || []).some((option) => option.model_id === modelId);
  });
  return matchedProvider?.provider_id || status?.active_provider?.provider_id || '';
}

export async function saveSpeechProviderSettings(context: ProviderSettingsActionContext) {
  const workspaceId = context.settings?.workspace.workspace_id;
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
    const provider = await configureSpeechProvider({
      provider_id: providerId,
      audio_transcription_model_id: context.state.speechAudioModelId,
      conversation_model_id: context.state.speechConversationModelId
    });
    if (context.getSettings()?.workspace.workspace_id !== workspaceId || !context.settings) return;
    const settings = { ...context.getSettings()!, provider };
    context.setSettings(settings);
    syncSettingsPanelDraft(context.state, settings, { speech: true });
    clearSettingsDrafts('.settings-speech-model-accordion');
    context.setNotice({ tone: 'success', message: 'Speech model settings updated.' });
  } catch (error) {
    context.state.speechProviderError = error instanceof Error ? error.message : 'Unable to update speech model settings.';
  } finally {
    context.state.isSavingSpeechProvider = false;
    context.render();
  }
}
