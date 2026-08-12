import { getProviderSubscriptionUsage, type PlatformSettings } from './adminApi';
import type { SettingsPanelState } from './settingsPanel';

export function createProviderUsageController(context: {
  getSettings: () => PlatformSettings | null;
  render: () => void;
  state: SettingsPanelState;
}) {
  let loadedWorkspaceId = '';

  function reset() {
    loadedWorkspaceId = '';
    context.state.providerUsageItems = [];
    context.state.providerUsageError = '';
    context.state.isLoadingProviderUsage = false;
  }

  async function ensureLoaded(force = false) {
    const settings = context.getSettings();
    const workspaceId = settings?.workspace.workspace_id || '';
    const provider = settings?.provider.active_provider || null;
    if (!workspaceId || !provider?.capabilities?.supports_subscription_usage) {
      reset();
      return;
    }
    if (context.state.isLoadingProviderUsage || (!force && loadedWorkspaceId === workspaceId)) {
      return;
    }
    context.state.isLoadingProviderUsage = true;
    context.state.providerUsageError = '';
    context.render();
    try {
      const payload = await getProviderSubscriptionUsage();
      if (context.getSettings()?.workspace.workspace_id !== workspaceId) {
        return;
      }
      context.state.providerUsageItems = payload.items;
      loadedWorkspaceId = workspaceId;
    } catch (error) {
      context.state.providerUsageError = error instanceof Error ? error.message : 'Provider usage unavailable';
    } finally {
      context.state.isLoadingProviderUsage = false;
      context.render();
    }
  }

  return {
    ensureLoaded,
    refresh: () => ensureLoaded(true),
    reset
  };
}
