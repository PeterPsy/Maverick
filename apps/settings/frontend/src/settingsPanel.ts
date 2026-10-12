import type { PlatformSettings } from './adminApi';
import type { SettingsPanelState } from './settingsDrafts';
import { computerUseSettingsHtml } from './computerUseSettings';
import { voicePageHtml } from './voicePage';
import { agenticRuntimeSettingsCardHtml } from './modelsPage';

export function settingsPanelHtml(settings: PlatformSettings | null, state: SettingsPanelState, section = 'models') {
  if (!settings) return '<section class="settings-card"><p role="alert">Settings unavailable.</p></section>';
  if (section === 'computer-use') return computerUseSettingsHtml(settings, state.computerUse);
  if (section === 'voice') return voicePageHtml(settings, state);
  return agenticRuntimeSettingsCardHtml(settings.agentic_admin || null, state, settings.provider.execution_families,
    settings.provider.native_agents?.items || [], settings.user.platform_role === 'admin');
}
