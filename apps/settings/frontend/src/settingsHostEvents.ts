let hostVisible = true;

export const settingsHostVisible = () => hostVisible && !document.hidden;

export function bindSettingsHostEvents(context: {
  navigate: (params: Record<string, unknown>) => void;
  visibilityChanged: (visible: boolean) => void;
}) {
  window.addEventListener('message', (event) => {
    if (event.source !== window.parent || event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
    const payload = event.data as { app_id?: string; params?: Record<string, unknown>; type?: string; visible?: boolean };
    if (payload.type === 'maverick.app.visibility-changed' && payload.app_id === 'settings') {
      hostVisible = payload.visible === true;
      context.visibilityChanged(settingsHostVisible());
    }
    if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'settings')) context.navigate(payload.params || {});
  });
  document.addEventListener('visibilitychange', () => context.visibilityChanged(settingsHostVisible()));
  window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'settings' }, '*');
}
