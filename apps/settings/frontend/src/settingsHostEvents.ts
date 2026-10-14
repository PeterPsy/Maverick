import { isExactLoopinoParentMessage } from '@loopino/pwa-cache';
import { applySettingsTheme } from './settingsTheme';

let hostVisible = true;

export const settingsHostVisible = () => hostVisible && !document.hidden;

export function bindSettingsHostEvents(context: {
  navigate: (params: Record<string, unknown>) => void;
  visibilityChanged: (visible: boolean) => void;
}) {
  window.addEventListener('message', (event) => {
    if (!isExactLoopinoParentMessage(event) || !event.data || typeof event.data !== 'object') return;
    const payload = event.data as { app_id?: string; params?: Record<string, unknown>; type?: string; visible?: boolean; theme?: unknown };
    if (payload.type === 'loopino.shell.theme-changed' || (payload.type === 'loopino.app.navigate' && (!payload.app_id || payload.app_id === 'settings'))) applySettingsTheme(payload.theme);
    if (payload.type === 'loopino.app.visibility-changed' && payload.app_id === 'settings') {
      hostVisible = payload.visible === true;
      context.visibilityChanged(settingsHostVisible());
    }
    if (payload.type === 'loopino.app.navigate' && (!payload.app_id || payload.app_id === 'settings')) context.navigate(payload.params || {});
  });
  document.addEventListener('visibilitychange', () => context.visibilityChanged(settingsHostVisible()));
  window.parent?.postMessage({ type: 'loopino.app.ready', app_id: 'settings' }, '*');
}
