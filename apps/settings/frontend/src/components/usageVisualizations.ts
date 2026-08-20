import type { UsageTimeSeriesPayload } from '../adminApi';
import { mountUsageHistoryCharts, unmountUsageHistoryCharts } from './usageHistoryCharts';
import { mountUsageLimitGauges, unmountUsageLimitGauges } from './usageLimitGauges';

export function unmountUsageVisualizations() {
  unmountUsageLimitGauges();
  unmountUsageHistoryCharts();
}

export function mountUsageVisualizations(options: {
  hourly: UsageTimeSeriesPayload | null;
  daily: UsageTimeSeriesPayload | null;
  isLoading: boolean;
}) {
  mountUsageLimitGauges();
  mountUsageHistoryCharts(options);
}
