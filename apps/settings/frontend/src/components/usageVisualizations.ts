import type { PlatformSettings, UsageTimeSeriesPayload } from '../adminApi';
import type { UsageHistoryFilters } from '../usageHistoryFilters';
import { mountUsageHistoryCharts, unmountUsageHistoryCharts } from './usageHistoryCharts';

export function unmountUsageVisualizations() {
  unmountUsageHistoryCharts();
}

export function mountUsageVisualizations(options: {
  history: UsageTimeSeriesPayload | null;
  filters: UsageHistoryFilters;
  isLoading: boolean;
  onFiltersChange: (patch: Partial<UsageHistoryFilters>) => void;
  settings: PlatformSettings | null;
}) {
  mountUsageHistoryCharts(options);
}
