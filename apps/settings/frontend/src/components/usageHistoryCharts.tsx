import React, { useId } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { PlatformSettings, UsageTimeSeriesItem, UsageTimeSeriesPayload, UsageTimeSeriesProviderFacet } from '../adminApi';
import {
  USAGE_HISTORY_METRICS,
  USAGE_HISTORY_TIME_RANGES,
  usageCatalogFacets,
  usageHistoryTimeRange,
  usageMetricLabel,
  usageMetricValue,
  type UsageHistoryFilters,
  type UsageHistoryMetric,
} from '../usageHistoryFilters';

const mountedRoots = new Map<Element, Root>();
const tokenNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export function unmountUsageHistoryCharts() {
  mountedRoots.forEach((root) => root.unmount());
  mountedRoots.clear();
}

export function mountUsageHistoryCharts(options: {
  history: UsageTimeSeriesPayload | null;
  filters: UsageHistoryFilters;
  isLoading: boolean;
  onFiltersChange: (patch: Partial<UsageHistoryFilters>) => void;
  settings: PlatformSettings | null;
}) {
  const filtersElement = document.querySelector<HTMLElement>('[data-usage-history-filters]');
  if (filtersElement) {
    const root = createRoot(filtersElement);
    root.render(<UsageHistoryFilterControls {...options} />);
    mountedRoots.set(filtersElement, root);
  }
  const chartElement = document.querySelector<HTMLElement>('[data-usage-history-chart]');
  if (chartElement) {
    const root = createRoot(chartElement);
    root.render(
      <UsageHistoryChart
        isLoading={options.isLoading}
        metric={options.filters.metric}
        payload={options.history}
        resolution={usageHistoryTimeRange(options.filters.timeRange).resolution}
      />,
    );
    mountedRoots.set(chartElement, root);
  }
}

export function UsageHistoryFilterControls({
  filters,
  history,
  isLoading,
  onFiltersChange,
  settings,
}: {
  filters: UsageHistoryFilters;
  history: UsageTimeSeriesPayload | null;
  isLoading: boolean;
  onFiltersChange: (patch: Partial<UsageHistoryFilters>) => void;
  settings: PlatformSettings | null;
}) {
  const fieldId = useId();
  const facets = mergeProviderFacets(usageCatalogFacets(settings), history);
  const providerIds = uniqueSorted([...facets.map((facet) => facet.provider_id), filters.providerId]);
  const modelIds = uniqueSorted([
    ...facets
      .filter((facet) => !filters.providerId || facet.provider_id === filters.providerId)
      .flatMap((facet) => facet.model_ids),
    filters.modelId,
  ]);
  return (
    <div className="settings-usage-filter-controls">
      <div className="settings-usage-filter-grid">
        <UsageFilter label="Metric" id={`${fieldId}-metric`}>
          <select
            disabled={isLoading}
            id={`${fieldId}-metric`}
            onChange={(event) => onFiltersChange({ metric: event.currentTarget.value as UsageHistoryMetric })}
            value={filters.metric}
          >
            {USAGE_HISTORY_METRICS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </UsageFilter>
        <UsageFilter label="Provider" id={`${fieldId}-provider`}>
          <select
            disabled={isLoading}
            id={`${fieldId}-provider`}
            onChange={(event) => onFiltersChange({ providerId: event.currentTarget.value, modelId: '' })}
            value={filters.providerId}
          >
            <option value="">All providers</option>
            {providerIds.map((providerId) => <option key={providerId} value={providerId}>{providerId}</option>)}
          </select>
        </UsageFilter>
        <UsageFilter label="Model" id={`${fieldId}-model`}>
          <select
            disabled={isLoading || modelIds.length === 0}
            id={`${fieldId}-model`}
            onChange={(event) => onFiltersChange({ modelId: event.currentTarget.value })}
            value={filters.modelId}
          >
            <option value="">All models</option>
            {modelIds.map((modelId) => <option key={modelId} value={modelId}>{modelId}</option>)}
          </select>
        </UsageFilter>
      </div>
      <fieldset className="settings-usage-time-range">
        <legend>Time range</legend>
        <div className="settings-usage-time-range-options">
          {USAGE_HISTORY_TIME_RANGES.map((option) => {
            const selected = filters.timeRange === option.value;
            return (
              <button
                aria-pressed={selected}
                className={selected ? 'is-selected' : ''}
                disabled={isLoading}
                key={option.value}
                onClick={() => onFiltersChange({ timeRange: option.value })}
                type="button"
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </fieldset>
    </div>
  );
}

export function UsageHistoryChart({
  isLoading,
  metric,
  payload,
  resolution,
}: {
  isLoading: boolean;
  metric: UsageHistoryMetric;
  payload: UsageTimeSeriesPayload | null;
  resolution: 'hour' | 'day';
}) {
  const titleId = useId();
  if (!payload && isLoading) {
    return <div className="settings-usage-chart-state" role="status"><span className="settings-usage-chart-loader" />Loading token history…</div>;
  }
  if (!payload) {
    return <div className="settings-usage-chart-state">Usage history is not available yet.</div>;
  }

  const items = payload.items || [];
  const metricLabel = usageMetricLabel(metric);
  const metricTotal = usageMetricValue(payload.totals, metric);
  const maxTokens = Math.max(1, ...items.map((item) => usageMetricValue(item, metric)));
  const width = 720;
  const chartTop = 12;
  const baseline = 132;
  const chartHeight = baseline - chartTop;
  const horizontalPadding = 12;
  const plotWidth = width - horizontalPadding * 2;
  const slotWidth = plotWidth / Math.max(1, items.length);
  const barWidth = Math.max(3, slotWidth * 0.64);
  const tickStride = Math.max(1, Math.ceil(items.length / 6));
  const chartTitle = `${resolution === 'hour' ? 'Hourly' : 'Daily'} ${metricLabel.toLowerCase()}: ${formatTokens(metricTotal)} tokens`;

  return (
    <div className="settings-usage-chart">
      <div className="settings-usage-chart-total">
        <strong>{formatTokens(metricTotal)}</strong>
        <span>{metricLabel.toLowerCase()} tokens · {items.reduce((total, item) => total + item.sample_count, 0)} samples</span>
      </div>
      <svg aria-labelledby={titleId} className="settings-usage-chart-svg" role="img" viewBox={`0 0 ${width} 164`}>
        <title id={titleId}>{chartTitle}</title>
        <line className="settings-usage-chart-gridline" x1={horizontalPadding} x2={width - horizontalPadding} y1={baseline} y2={baseline} />
        {items.map((item, index) => {
          const tokens = usageMetricValue(item, metric);
          const height = tokens > 0 ? Math.max(2, tokens / maxTokens * chartHeight) : 0;
          const x = horizontalPadding + index * slotWidth + (slotWidth - barWidth) / 2;
          const labelVisible = index % tickStride === 0 || index === items.length - 1;
          return (
            <g key={item.bucket_start}>
              <rect
                aria-label={`${formatBucketTitle(item)}: ${formatTokens(tokens)} ${metricLabel.toLowerCase()} tokens`}
                className="settings-usage-chart-bar"
                height={height}
                rx={Math.min(3, barWidth / 3)}
                width={barWidth}
                x={x}
                y={baseline - height}
              >
                <title>{formatBucketTitle(item)} · {formatTokens(tokens)} {metricLabel.toLowerCase()} tokens</title>
              </rect>
              {labelVisible ? (
                <text className="settings-usage-chart-axis-label" textAnchor="middle" x={x + barWidth / 2} y={153}>
                  {formatBucketLabel(item.bucket_start, resolution)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <div className="settings-usage-chart-breakdown" aria-label="Token category totals">
        <UsageChartTotal label="Non-cached" selected={metric === 'non_cached_tokens'} value={usageMetricValue(payload.totals, 'non_cached_tokens')} />
        <UsageChartTotal label="Cached" selected={metric === 'cached_input_tokens'} value={payload.totals.cached_input_tokens} />
        <UsageChartTotal label="Processed" selected={metric === 'total_tokens'} value={payload.totals.total_tokens} />
        <UsageChartTotal label="Input" selected={metric === 'input_tokens'} value={payload.totals.input_tokens} />
        <UsageChartTotal label="Output" selected={metric === 'output_tokens'} value={payload.totals.output_tokens} />
        <UsageChartTotal label="Reasoning" selected={metric === 'reasoning_output_tokens'} value={payload.totals.reasoning_output_tokens} />
        {payload.totals.cache_write_input_tokens > 0 ? (
          <UsageChartTotal label="Cache write" selected={metric === 'cache_write_input_tokens'} value={payload.totals.cache_write_input_tokens} />
        ) : null}
      </div>
      <p className="settings-usage-chart-coverage">
        {payload.coverage_since ? `Coverage from ${formatDateTime(payload.coverage_since)}` : 'No metered usage in this period'} · UTC buckets
      </p>
    </div>
  );
}

function UsageFilter({ children, id, label }: { children: React.ReactNode; id: string; label: string }) {
  return <label className="settings-usage-filter" htmlFor={id}><span>{label}</span>{children}</label>;
}

function UsageChartTotal({ label, selected, value }: { label: string; selected: boolean; value: number }) {
  return <span className={selected ? 'is-selected' : ''}><small>{label}</small><strong>{formatTokens(value)}</strong></span>;
}

function mergeProviderFacets(
  catalogFacets: UsageTimeSeriesProviderFacet[],
  ...payloads: Array<UsageTimeSeriesPayload | null>
): UsageTimeSeriesProviderFacet[] {
  const models = new Map<string, Set<string>>();
  [...catalogFacets, ...payloads.flatMap((payload) => payload?.facets?.providers || [])].forEach((facet) => {
    const providerModels = models.get(facet.provider_id) || new Set<string>();
    facet.model_ids.forEach((modelId) => providerModels.add(modelId));
    models.set(facet.provider_id, providerModels);
  });
  return Array.from(models, ([provider_id, modelIds]) => ({
    provider_id,
    model_ids: Array.from(modelIds).sort((left, right) => left.localeCompare(right)),
  })).sort((left, right) => left.provider_id.localeCompare(right.provider_id));
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort((left, right) => left.localeCompare(right));
}

function formatTokens(value: number): string {
  return tokenNumber.format(Math.max(0, Number.isFinite(value) ? value : 0));
}

function formatBucketLabel(value: string, resolution: 'hour' | 'day'): string {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return '';
  return resolution === 'hour'
    ? timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : timestamp.toLocaleDateString([], { day: '2-digit', month: 'short' });
}

function formatBucketTitle(item: UsageTimeSeriesItem): string {
  return formatDateTime(item.bucket_start);
}

function formatDateTime(value: string): string {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? 'Unknown time' : timestamp.toLocaleString();
}
