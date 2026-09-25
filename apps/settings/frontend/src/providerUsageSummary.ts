import type { ProviderSubscriptionUsage, ProviderUsageWindow } from './adminApi';

type ProviderUsageSummaryState = {
  isLoadingProviderUsage: boolean;
  providerUsageError: string;
  providerUsageItems: ProviderSubscriptionUsage[];
};

export function providerUsageSummary(
  providerId: string,
  state: ProviderUsageSummaryState,
  nowEpochMilliseconds = Date.now()
): string {
  const usage = state.providerUsageItems.find((item) => item.provider_id === providerId);
  if (!usage) {
    if (state.isLoadingProviderUsage) {
      return 'Loading usage…';
    }
    if (state.providerUsageError) {
      return 'Usage unavailable';
    }
    return 'Usage limit not reported';
  }
  if (!usage.available) {
    return 'Usage unavailable';
  }
  const limits = usage.limits.map((limit) => ({
    limit,
    windows: [limit.primary_window, limit.secondary_window]
      .filter((window): window is ProviderUsageWindow => window !== null),
  })).filter(({ windows }) => windows.length > 0);
  if (!limits.length) {
    return 'Usage limit not reported';
  }
  const showLimitLabels = limits.length > 1;
  return limits.map(({ limit, windows }) => {
    const prefix = showLimitLabels ? `${limit.label} — ` : '';
    return `${prefix}${windows.map((window) => usageWindowSummary(window, nowEpochMilliseconds)).join('; ')}`;
  }).join(' · ');
}

function usageWindowSummary(window: ProviderUsageWindow, nowEpochMilliseconds: number): string {
  const used = Math.min(100, Math.max(0, window.used_percent));
  const remaining = Math.max(0, 100 - used);
  const reset = formatUsageReset(window, nowEpochMilliseconds);
  return `${formatUsageWindow(window.limit_window_seconds)}: ${formatPercentage(used)} used · ${formatPercentage(remaining)} remaining before limit${reset ? ` · ${reset}` : ''}`;
}

function formatPercentage(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`;
}

function formatUsageWindow(seconds: number | null): string {
  if (!seconds || seconds <= 0) return 'Rolling window';
  if (seconds % 604800 === 0) return `${seconds / 604800}w window`;
  if (seconds % 86400 === 0) return `${seconds / 86400}d window`;
  if (seconds % 3600 === 0) return `${seconds / 3600}h window`;
  if (seconds % 60 === 0) return `${seconds / 60}m window`;
  return 'Rolling window';
}

function formatUsageReset(window: ProviderUsageWindow, nowEpochMilliseconds: number): string {
  let seconds: number | null = null;
  if (window.reset_at_epoch_seconds !== null) {
    seconds = Math.max(0, Math.ceil(window.reset_at_epoch_seconds - nowEpochMilliseconds / 1000));
  } else {
    seconds = window.reset_after_seconds;
  }
  if (seconds === null) return '';
  return `resets ${formatDuration(seconds)}`;
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return 'now';
  const roundedMinutes = Math.max(1, Math.ceil(seconds / 60));
  const days = Math.floor(roundedMinutes / 1440);
  const hours = Math.floor((roundedMinutes % 1440) / 60);
  const minutes = roundedMinutes % 60;
  if (days > 0) return `in ${days}d${hours > 0 ? ` ${hours}h` : ''}`;
  if (hours > 0) return `in ${hours}h${minutes > 0 ? ` ${minutes}m` : ''}`;
  return `in ${minutes}m`;
}
