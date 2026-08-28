import type { PlatformSettings, UsageTimeSeriesPayload } from '../adminApi';
import type { UsageHistoryFilters } from '../usageHistoryFilters';
import { mountUsageHistoryCharts, unmountUsageHistoryCharts } from './usageHistoryCharts';
import { mountUsageLimitGauges, unmountUsageLimitGauges } from './usageLimitGauges';

export function unmountUsageVisualizations() {
  unmountUsageLimitGauges();
  unmountUsageHistoryCharts();
}

export function mountUsageVisualizations(options: {
  history: UsageTimeSeriesPayload | null;
  filters: UsageHistoryFilters;
  isLoading: boolean;
  onFiltersChange: (patch: Partial<UsageHistoryFilters>) => void;
  settings: PlatformSettings | null;
}) {
  mountUsageLimitGauges();
  mountUsageHistoryCharts(options);
}
