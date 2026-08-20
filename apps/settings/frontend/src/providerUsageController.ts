import { getProviderSubscriptionUsage, getUsageTimeseries, type PlatformSettings } from './adminApi';
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
    context.state.hourlyUsage = null;
    context.state.dailyUsage = null;
    context.state.usageHistoryError = '';
    context.state.isLoadingUsageHistory = false;
  }

  async function ensureLoaded(force = false) {
    const settings = context.getSettings();
    const workspaceId = settings?.workspace.workspace_id || '';
    const provider = settings?.provider.active_provider || null;
    if (!workspaceId) {
      reset();
      return;
    }
    if (context.state.isLoadingProviderUsage || context.state.isLoadingUsageHistory || (!force && loadedWorkspaceId === workspaceId)) {
      return;
    }
    const supportsProviderUsage = Boolean(provider?.capabilities?.supports_subscription_usage);
    context.state.isLoadingProviderUsage = supportsProviderUsage;
    context.state.isLoadingUsageHistory = true;
    context.state.providerUsageError = '';
    context.state.usageHistoryError = '';
    if (!supportsProviderUsage) {
      context.state.providerUsageItems = [];
    }
    context.render();
    try {
      const [providerResult, hourlyResult, dailyResult] = await Promise.allSettled([
        supportsProviderUsage ? getProviderSubscriptionUsage() : Promise.resolve(null),
        getUsageTimeseries('hour', 24),
        getUsageTimeseries('day', 30)
      ]);
      if (context.getSettings()?.workspace.workspace_id !== workspaceId) {
        return;
      }
      if (providerResult.status === 'fulfilled' && providerResult.value) {
        context.state.providerUsageItems = providerResult.value.items;
      } else if (providerResult.status === 'rejected') {
        context.state.providerUsageError = providerResult.reason instanceof Error
          ? providerResult.reason.message
          : 'Provider usage unavailable';
      }
      if (hourlyResult.status === 'fulfilled') {
        context.state.hourlyUsage = hourlyResult.value;
      }
      if (dailyResult.status === 'fulfilled') {
        context.state.dailyUsage = dailyResult.value;
      }
      if (hourlyResult.status === 'rejected' || dailyResult.status === 'rejected') {
        const failure = hourlyResult.status === 'rejected' ? hourlyResult.reason : dailyResult.status === 'rejected' ? dailyResult.reason : null;
        context.state.usageHistoryError = failure instanceof Error ? failure.message : 'Token usage history unavailable';
      }
      loadedWorkspaceId = workspaceId;
    } finally {
      context.state.isLoadingProviderUsage = false;
      context.state.isLoadingUsageHistory = false;
      context.render();
    }
  }

  return {
    ensureLoaded,
    refresh: () => ensureLoaded(true),
    reset
  };
}
