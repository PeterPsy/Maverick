import React, { useId } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { UsageTimeSeriesItem, UsageTimeSeriesPayload } from '../adminApi';

const mountedRoots = new Map<Element, Root>();
const tokenNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export function unmountUsageHistoryCharts() {
  mountedRoots.forEach((root) => root.unmount());
  mountedRoots.clear();
}

export function mountUsageHistoryCharts(options: {
  hourly: UsageTimeSeriesPayload | null;
  daily: UsageTimeSeriesPayload | null;
  isLoading: boolean;
}) {
  document.querySelectorAll<HTMLElement>('[data-usage-history-chart]').forEach((element) => {
    const resolution = element.dataset.usageHistoryChart === 'hour' ? 'hour' : 'day';
    const payload = resolution === 'hour' ? options.hourly : options.daily;
    const root = createRoot(element);
    root.render(<UsageHistoryChart isLoading={options.isLoading} payload={payload} resolution={resolution} />);
    mountedRoots.set(element, root);
  });
}

export function UsageHistoryChart({
  isLoading,
  payload,
  resolution,
}: {
  isLoading: boolean;
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
  const maxTokens = Math.max(1, ...items.map((item) => item.total_tokens));
  const width = 720;
  const chartTop = 12;
  const baseline = 132;
  const chartHeight = baseline - chartTop;
  const horizontalPadding = 12;
  const plotWidth = width - horizontalPadding * 2;
  const slotWidth = plotWidth / Math.max(1, items.length);
  const barWidth = Math.max(3, slotWidth * 0.64);
  const tickStride = Math.max(1, Math.ceil(items.length / 6));
  const chartTitle = `${resolution === 'hour' ? 'Hourly' : 'Daily'} token consumption: ${formatTokens(payload.totals.total_tokens)} total tokens`;

  return (
    <div className="settings-usage-chart">
      <div className="settings-usage-chart-total">
        <strong>{formatTokens(payload.totals.total_tokens)}</strong>
        <span>tokens · {payload.items.reduce((total, item) => total + item.sample_count, 0)} samples</span>
      </div>
      <svg aria-labelledby={titleId} className="settings-usage-chart-svg" role="img" viewBox={`0 0 ${width} 164`}>
        <title id={titleId}>{chartTitle}</title>
        <line className="settings-usage-chart-gridline" x1={horizontalPadding} x2={width - horizontalPadding} y1={baseline} y2={baseline} />
        {items.map((item, index) => {
          const height = item.total_tokens > 0 ? Math.max(2, item.total_tokens / maxTokens * chartHeight) : 0;
          const x = horizontalPadding + index * slotWidth + (slotWidth - barWidth) / 2;
          const labelVisible = index % tickStride === 0 || index === items.length - 1;
          return (
            <g key={item.bucket_start}>
              <rect
                aria-label={`${formatBucketTitle(item)}: ${formatTokens(item.total_tokens)} tokens`}
                className="settings-usage-chart-bar"
                height={height}
                rx={Math.min(3, barWidth / 3)}
                width={barWidth}
                x={x}
                y={baseline - height}
              >
                <title>{formatBucketTitle(item)} · {formatTokens(item.total_tokens)} tokens</title>
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
        <UsageChartTotal label="Input" value={payload.totals.input_tokens} />
        <UsageChartTotal label="Cached" value={payload.totals.cached_input_tokens} />
        <UsageChartTotal label="Output" value={payload.totals.output_tokens} />
        <UsageChartTotal label="Reasoning" value={payload.totals.reasoning_output_tokens} />
      </div>
      <p className="settings-usage-chart-coverage">
        {payload.coverage_since ? `Coverage from ${formatDateTime(payload.coverage_since)}` : 'No metered usage in this period'} · UTC buckets
      </p>
    </div>
  );
}

function UsageChartTotal({ label, value }: { label: string; value: number }) {
  return <span><small>{label}</small><strong>{formatTokens(value)}</strong></span>;
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
