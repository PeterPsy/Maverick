import {
  configureActiveProvider,
  configureHostedProvider,
  getPlatformSettings,
  type PlatformSettings
} from './adminApi';
import { syncSettingsPanelDraft, type SettingsPanelState } from './settingsPanel';

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
    context.state.hostedProviderError = 'Hosted provider not loaded.';
    context.render();
    return;
  }
  context.state.isSavingHostedProvider = true;
  context.state.hostedProviderError = '';
  context.render();
  try {
    await configureHostedProvider({
      provider_id: providerId,
      model_id: context.state.hostedDraftModelId
    });
    const settings = await getPlatformSettings();
    context.setSettings(settings);
    syncSettingsPanelDraft(context.state, settings);
    context.setNotice({ tone: 'success', message: 'Hosted model settings updated.' });
  } catch (error) {
    context.state.hostedProviderError = error instanceof Error ? error.message : 'Unable to update hosted model settings.';
  } finally {
    context.state.isSavingHostedProvider = false;
    context.render();
  }
}
