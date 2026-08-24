import { getProviderSubscriptionUsage, getUsageTimeseries, type PlatformSettings } from './adminApi';
import type { SettingsPanelState } from './settingsPanel';
import {
  defaultUsageHistoryFilters,
  mergeUsageHistoryFilters,
  type UsageHistoryFilters,
} from './usageHistoryFilters';

export function createProviderUsageController(context: {
  getSettings: () => PlatformSettings | null;
  render: () => void;
  state: SettingsPanelState;
}) {
  let loadedWorkspaceId = '';
  let providerRequestId = 0;
  let historyRequestId = 0;

  function reset() {
    loadedWorkspaceId = '';
    providerRequestId += 1;
    historyRequestId += 1;
    context.state.providerUsageItems = [];
    context.state.providerUsageError = '';
    context.state.isLoadingProviderUsage = false;
    context.state.hourlyUsage = null;
    context.state.dailyUsage = null;
    context.state.usageHistoryFilters = defaultUsageHistoryFilters();
    context.state.usageHistoryError = '';
    context.state.isLoadingUsageHistory = false;
  }

  async function ensureLoaded(force = false) {
    const settings = context.getSettings();
    const workspaceId = settings?.workspace.workspace_id || '';
    if (!workspaceId) {
      reset();
      return;
    }
    if (!force && loadedWorkspaceId === workspaceId) {
      return;
    }
    if (loadedWorkspaceId && loadedWorkspaceId !== workspaceId) {
      context.state.usageHistoryFilters = defaultUsageHistoryFilters();
    }
    loadedWorkspaceId = workspaceId;
    const supportsProviderUsage = Boolean(settings?.provider.active_provider?.capabilities?.supports_subscription_usage);
    await Promise.all([
      loadProviderUsage(workspaceId, supportsProviderUsage),
      loadUsageHistory(workspaceId),
    ]);
  }

  async function loadProviderUsage(workspaceId: string, supported: boolean) {
    const requestId = ++providerRequestId;
    context.state.providerUsageError = '';
    if (!supported) {
      context.state.providerUsageItems = [];
      context.state.isLoadingProviderUsage = false;
      context.render();
      return;
    }
    context.state.isLoadingProviderUsage = true;
    context.render();
    try {
      const payload = await getProviderSubscriptionUsage();
      if (isCurrentWorkspace(workspaceId) && requestId === providerRequestId) {
        context.state.providerUsageItems = payload.items;
      }
    } catch (error) {
      if (isCurrentWorkspace(workspaceId) && requestId === providerRequestId) {
        context.state.providerUsageError = error instanceof Error ? error.message : 'Provider usage unavailable';
      }
    } finally {
      if (isCurrentWorkspace(workspaceId) && requestId === providerRequestId) {
        context.state.isLoadingProviderUsage = false;
        context.render();
      }
    }
  }

  async function loadUsageHistory(workspaceId: string, clearExisting = false) {
    const requestId = ++historyRequestId;
    const filters = context.state.usageHistoryFilters;
    const queryFilters = { providerId: filters.providerId, modelId: filters.modelId };
    context.state.isLoadingUsageHistory = true;
    context.state.usageHistoryError = '';
    if (clearExisting) {
      context.state.hourlyUsage = null;
      context.state.dailyUsage = null;
    }
    context.render();
    try {
      const [hourlyResult, dailyResult] = await Promise.allSettled([
        getUsageTimeseries('hour', filters.hourlyPeriods, queryFilters),
        getUsageTimeseries('day', filters.dailyPeriods, queryFilters),
      ]);
      if (!isCurrentWorkspace(workspaceId) || requestId !== historyRequestId) {
        return;
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
    } finally {
      if (isCurrentWorkspace(workspaceId) && requestId === historyRequestId) {
        context.state.isLoadingUsageHistory = false;
        context.render();
      }
    }
  }

  function updateUsageHistoryFilters(patch: Partial<UsageHistoryFilters>): Promise<void> {
    const previous = context.state.usageHistoryFilters;
    const next = mergeUsageHistoryFilters(previous, patch);
    if (sameFilters(previous, next)) {
      return Promise.resolve();
    }
    context.state.usageHistoryFilters = next;
    const queryChanged = previous.providerId !== next.providerId
      || previous.modelId !== next.modelId
      || previous.hourlyPeriods !== next.hourlyPeriods
      || previous.dailyPeriods !== next.dailyPeriods;
    const workspaceId = context.getSettings()?.workspace.workspace_id || '';
    if (!queryChanged || !workspaceId) {
      context.render();
      return Promise.resolve();
    }
    return loadUsageHistory(workspaceId, true);
  }

  function isCurrentWorkspace(workspaceId: string): boolean {
    return context.getSettings()?.workspace.workspace_id === workspaceId;
  }

  return {
    ensureLoaded,
    refresh: () => ensureLoaded(true),
    reset,
    updateUsageHistoryFilters,
  };
}

function sameFilters(left: UsageHistoryFilters, right: UsageHistoryFilters): boolean {
  return left.metric === right.metric
    && left.providerId === right.providerId
    && left.modelId === right.modelId
    && left.hourlyPeriods === right.hourlyPeriods
    && left.dailyPeriods === right.dailyPeriods;
}
