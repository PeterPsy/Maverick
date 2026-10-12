import { bindControl } from './controlBindings';

export type SettingsPanelActions = {
  onActivateNativeProvider: (providerId: string) => void;
  onClearAllRuntimeSessions: () => void;
  onClearRuntimeSession: (sessionId: string) => void;
  onLogout: () => void;
  onHostedProviderRoutingChanged: (modelId: string, field: string, value: string | boolean) => void;
  onSaveAgenticBinding: (
    definitionId: string,
    options?: { enabled?: boolean }
  ) => void;
  onSaveHostedProviderSettings: (modelId?: string) => void;
  onRefreshProviderUsage: () => void;
  onSaveSpeechProviderSettings: () => void;
  onSpeechAudioModelChanged: (modelId: string) => void;
  onSpeechConversationModelChanged: (modelId: string) => void;
};

export function bindSettingsPanelEvents(actions: SettingsPanelActions) {
  document.querySelectorAll<HTMLButtonElement>('[data-native-provider-activate]').forEach((button) => {
    bindControl(button, 'click', () => {
      actions.onActivateNativeProvider(button.dataset.nativeProviderActivate || '');
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-agentic-binding-save]').forEach((button) => {
    bindControl(button, 'click', () => {
      actions.onSaveAgenticBinding(
        button.dataset.agenticDefinitionId || ''
      );
    });
  });
  document.querySelectorAll<HTMLInputElement>('[data-agentic-model-toggle]').forEach((toggle) => {
    bindControl(toggle, 'click', (event) => event.stopPropagation());
    bindControl(toggle.closest('label'), 'click', (event) => event.stopPropagation());
    bindControl(toggle, 'change', () => {
      const enable = toggle.checked;
      actions.onSaveAgenticBinding(
        toggle.dataset.agenticDefinitionId || '',
        { enabled: enable }
      );
    });
  });
  bindControl(document.getElementById('settings-speech-audio-model'), 'change', (event) => {
    actions.onSpeechAudioModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  bindControl(document.getElementById('settings-speech-conversation-model'), 'change', (event) => {
    actions.onSpeechConversationModelChanged((event.currentTarget as HTMLSelectElement).value);
  });
  document.querySelectorAll<HTMLButtonElement>('[data-speech-save]').forEach((button) => {
    bindControl(button, 'click', () => {
      actions.onSaveSpeechProviderSettings();
    });
  });
  bindControl(document.getElementById('settings-speech-save'), 'click', () => {
    actions.onSaveSpeechProviderSettings();
  });
  document.querySelectorAll<HTMLDetailsElement>('[data-settings-model-accordion]').forEach((details) => {
    bindControl(details, 'toggle', () => {
      if (!details.open) return;
      document.querySelectorAll<HTMLDetailsElement>('[data-settings-model-accordion]').forEach((otherDetails) => {
        if (otherDetails !== details) {
          otherDetails.open = false;
        }
      });
    });
  });
  document.querySelectorAll<HTMLElement>('[data-openrouter-routing]').forEach((element) => {
    bindControl(element, 'change', (event) => {
      const target = event.currentTarget as HTMLInputElement | HTMLSelectElement;
      const modelId =
        target.dataset.hostedModelId ||
        target.closest<HTMLElement>('[data-hosted-model-accordion]')?.dataset.hostedModelAccordion ||
        '';
      actions.onHostedProviderRoutingChanged(
        modelId,
        target.dataset.openrouterRouting || '',
        target instanceof HTMLInputElement && target.type === 'checkbox' ? target.checked : target.value
      );
    });
  });
  bindControl(document.getElementById('settings-refresh-usage-history'), 'click', actions.onRefreshProviderUsage);
  document.querySelectorAll<HTMLButtonElement>('[data-hosted-provider-save]').forEach((button) => {
    bindControl(button, 'click', () => actions.onSaveHostedProviderSettings(button.dataset.hostedProviderSave || ''));
  });
  bindControl(document.getElementById('settings-logout'), 'click', actions.onLogout);
  bindControl(document.getElementById('settings-clear-all-runtime'), 'click', actions.onClearAllRuntimeSessions);
  document.querySelectorAll<HTMLButtonElement>('[data-runtime-clear]').forEach((button) => {
    bindControl(button, 'click', () => actions.onClearRuntimeSession(button.dataset.runtimeClear || ''));
  });
}
