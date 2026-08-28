import type { PlatformSettings, ProviderItem, UsageTimeSeriesProviderFacet, UsageTokenTotals } from './adminApi';

export type UsageHistoryMetric =
  | 'non_cached_tokens'
  | 'total_tokens'
  | 'cached_input_tokens'
  | 'input_tokens'
  | 'output_tokens'
  | 'reasoning_output_tokens'
  | 'cache_write_input_tokens';

export type UsageHistoryResolution = 'hour' | 'day';

export const USAGE_HISTORY_TIME_RANGES = [
  { value: '6h', label: '6 hours', resolution: 'hour', periods: 6 },
  { value: '12h', label: '12 hours', resolution: 'hour', periods: 12 },
  { value: '24h', label: '24 hours', resolution: 'hour', periods: 24 },
  { value: '3d', label: '3 days', resolution: 'hour', periods: 72 },
  { value: '7d', label: '7 days', resolution: 'day', periods: 7 },
  { value: '30d', label: '30 days', resolution: 'day', periods: 30 },
  { value: '90d', label: '90 days', resolution: 'day', periods: 90 },
  { value: '180d', label: '180 days', resolution: 'day', periods: 180 },
  { value: '1y', label: '1 year', resolution: 'day', periods: 365 },
] as const satisfies ReadonlyArray<{
  value: string;
  label: string;
  resolution: UsageHistoryResolution;
  periods: number;
}>;

export type UsageHistoryTimeRange = (typeof USAGE_HISTORY_TIME_RANGES)[number]['value'];

export type UsageHistoryFilters = {
  metric: UsageHistoryMetric;
  providerId: string;
  modelId: string;
  timeRange: UsageHistoryTimeRange;
};

export const USAGE_HISTORY_METRICS: ReadonlyArray<{ value: UsageHistoryMetric; label: string }> = [
  { value: 'non_cached_tokens', label: 'Non-cached' },
  { value: 'total_tokens', label: 'Processed total' },
  { value: 'cached_input_tokens', label: 'Cached input' },
  { value: 'input_tokens', label: 'Uncached input' },
  { value: 'output_tokens', label: 'Output' },
  { value: 'reasoning_output_tokens', label: 'Reasoning output' },
  { value: 'cache_write_input_tokens', label: 'Cache write' },
];

export function defaultUsageHistoryFilters(): UsageHistoryFilters {
  return {
    metric: 'non_cached_tokens',
    providerId: '',
    modelId: '',
    timeRange: '24h',
  };
}

export function mergeUsageHistoryFilters(
  current: UsageHistoryFilters,
  patch: Partial<UsageHistoryFilters>,
): UsageHistoryFilters {
  const metric = USAGE_HISTORY_METRICS.some((option) => option.value === patch.metric)
    ? patch.metric as UsageHistoryMetric
    : current.metric;
  const timeRange = USAGE_HISTORY_TIME_RANGES.some((option) => option.value === patch.timeRange)
    ? patch.timeRange as UsageHistoryTimeRange
    : current.timeRange;
  return {
    metric,
    providerId: textOrCurrent(patch.providerId, current.providerId),
    modelId: textOrCurrent(patch.modelId, current.modelId),
    timeRange,
  };
}

export function usageHistoryTimeRange(value: string): (typeof USAGE_HISTORY_TIME_RANGES)[number] {
  return USAGE_HISTORY_TIME_RANGES.find((option) => option.value === value)
    || USAGE_HISTORY_TIME_RANGES[2];
}

export function usageMetricValue(tokens: UsageTokenTotals, metric: UsageHistoryMetric): number {
  if (metric === 'non_cached_tokens') {
    return Math.max(0, finite(tokens.total_tokens) - finite(tokens.cached_input_tokens));
  }
  return Math.max(0, finite(tokens[metric]));
}

export function usageMetricLabel(metric: UsageHistoryMetric): string {
  return USAGE_HISTORY_METRICS.find((option) => option.value === metric)?.label || 'Non-cached';
}

export function usageCatalogFacets(settings: PlatformSettings | null): UsageTimeSeriesProviderFacet[] {
  const modelsByProvider = new Map<string, Set<string>>();
  const addProvider = (provider: ProviderItem | null | undefined, extraModelIds: string[] = []) => {
    if (!provider?.provider_id) return;
    const models = modelsByProvider.get(provider.provider_id) || new Set<string>();
    provider.model_options.forEach((option) => option.model_id && models.add(option.model_id));
    extraModelIds.forEach((modelId) => modelId && models.add(modelId));
    modelsByProvider.set(provider.provider_id, models);
  };
  const providerStatus = settings?.provider;
  addProvider(
    providerStatus?.active_provider,
    [
      providerStatus?.model_settings?.selected_model_id || '',
      ...(providerStatus?.model_settings?.available_models || []).map((option) => option.model_id),
    ],
  );
  providerStatus?.available_providers?.forEach((provider) => addProvider(provider));
  const hostedStatus = providerStatus?.hosted_text;
  addProvider(
    hostedStatus?.active_provider,
    [
      hostedStatus?.model_settings?.selected_model_id || '',
      ...(hostedStatus?.model_settings?.available_models || []).map((option) => option.model_id),
    ],
  );
  hostedStatus?.available_providers.forEach((provider) => addProvider(provider));
  settings?.agentic_admin?.items.forEach((item) => {
    const models = modelsByProvider.get(item.model_provider_id) || new Set<string>();
    if (item.model_id) models.add(item.model_id);
    modelsByProvider.set(item.model_provider_id, models);
  });
  return Array.from(modelsByProvider, ([provider_id, modelIds]) => ({
    provider_id,
    model_ids: Array.from(modelIds).sort((left, right) => left.localeCompare(right)),
  })).sort((left, right) => left.provider_id.localeCompare(right.provider_id));
}

function finite(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

function textOrCurrent(value: string | undefined, current: string): string {
  return typeof value === 'string' ? value.trim() : current;
}
