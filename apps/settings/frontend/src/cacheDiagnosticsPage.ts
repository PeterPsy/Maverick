import type { PwaCacheDashboard, PwaCacheMetricsSnapshot } from '@maverick/pwa-cache';
import type { CacheDiagnosticsViewState } from './cacheDiagnosticsController';
import { escapeHtml } from './html';

export function cacheDiagnosticsPageHtml(state: CacheDiagnosticsViewState): string {
  const { confirmClear, dashboard, error, isClearing, isLoading } = state;
  const actionLabel = isClearing ? 'Clearing…' : confirmClear ? 'Confirm clear cache' : 'Clear cache';
  return `<section class="settings-card settings-cache-diagnostics" aria-busy="${isLoading || isClearing}">
    <div class="settings-heading">
      <div>
        <span class="settings-kicker">This browser</span>
        <h3>Maverick cache</h3>
      </div>
      <span class="settings-pill settings-pill-muted">Disposable</span>
    </div>
    <p class="settings-card-copy">Inspect aggregate cache usage for this browser container. Cached entries and file copies are rebuildable and never authorize server actions.</p>
    ${error ? `<div class="settings-cache-diagnostics__error" role="alert">${escapeHtml(error)}</div>` : ''}
    ${dashboardHtml(dashboard, isLoading)}
    <div class="settings-cache-diagnostics__actions">
      <button class="settings-secondary" id="refresh-pwa-cache" type="button" ${isLoading || isClearing ? 'disabled' : ''}>
        <span class="material-symbols-rounded" aria-hidden="true">refresh</span>
        Refresh
      </button>
      <button class="${confirmClear ? 'settings-danger' : 'settings-secondary'}" id="clear-pwa-cache" type="button" ${isLoading || isClearing ? 'disabled' : ''}>
        <span class="material-symbols-rounded" aria-hidden="true">delete_sweep</span>
        ${actionLabel}
      </button>
      ${confirmClear ? `<button class="settings-secondary" id="cancel-clear-pwa-cache" type="button">Cancel</button>` : ''}
    </div>
    <p class="settings-cache-diagnostics__note">Clear cache removes only Maverick's structured data and versioned file cache from this browser container. It does not delete server files, static app assets, or unrelated origin storage.</p>
  </section>`;
}

function dashboardHtml(dashboard: PwaCacheDashboard | null, isLoading: boolean): string {
  if (!dashboard || isLoading) {
    return `<div class="settings-cache-diagnostics__grid" aria-label="Loading cache diagnostics">
      ${metricHtml('Cache data', '—')}
      ${metricHtml('Entries', '—')}
      ${metricHtml('Origin usage', '—')}
      ${metricHtml('Origin quota', '—')}
    </div>`;
  }
  const { diagnostics, metrics } = dashboard;
  return `<div class="settings-cache-diagnostics__section">
    <h4>Storage and quota</h4>
    <div class="settings-cache-diagnostics__grid">
    ${metricHtml('Cache data', formatBytes(diagnostics.cacheBytes))}
    ${metricHtml('Entries', diagnostics.entryCount.toLocaleString())}
    ${metricHtml('Structured data', formatBytes(diagnostics.structuredCacheBytes))}
    ${metricHtml('Structured entries', diagnostics.structuredEntryCount.toLocaleString())}
    ${metricHtml('File data', formatBytes(diagnostics.fileCacheBytes))}
    ${metricHtml('File entries', diagnostics.fileCacheEntryCount.toLocaleString())}
    ${metricHtml('Origin usage', formatOptionalBytes(diagnostics.originUsageBytes))}
    ${metricHtml('Origin quota', formatOptionalBytes(diagnostics.originQuotaBytes))}
    ${metricHtml('Backend', diagnostics.backend === 'indexeddb' ? 'IndexedDB' : 'Memory fallback')}
    ${metricHtml('File storage', diagnostics.fileCacheAvailable ? 'OPFS available' : 'Unavailable')}
    ${metricHtml('Pending cleanup', diagnostics.pendingCleanupCount.toLocaleString())}
    </div>
  </div>
  ${activityHtml(metrics)}
  ${resilienceHtml(metrics)}`;
}

function activityHtml(metrics: PwaCacheMetricsSnapshot): string {
  const counters = metrics.counters;
  return `<div class="settings-cache-diagnostics__section">
    <h4>Cache activity</h4>
    <p>Aggregate events in this browser since ${escapeHtml(formatTimestamp(metrics.windowStartedAt))}.</p>
    <div class="settings-cache-diagnostics__grid">
      ${metricHtml('Static hit / miss', ratio(counters.pwa_static_cache_hit, counters.pwa_static_cache_miss))}
      ${metricHtml('Data hit / miss', ratio(counters.pwa_data_cache_hit, counters.pwa_data_cache_miss))}
      ${metricHtml('Data cache errors', formatCount(counters.pwa_data_cache_error))}
      ${metricHtml('Stale / expired', ratio(counters.pwa_data_cache_stale, counters.pwa_data_cache_expired))}
      ${metricHtml('Revalidated unchanged', formatCount(counters.pwa_revalidate_not_modified))}
      ${metricHtml('Revalidated changed', formatCount(counters.pwa_revalidate_modified))}
      ${metricHtml('Revalidation errors', formatCount(counters.pwa_revalidate_error))}
      ${metricHtml('File hit / miss', ratio(counters.pwa_file_cache_hit, counters.pwa_file_cache_miss))}
      ${metricHtml('File writes / ready', ratio(counters.pwa_file_cache_write, counters.pwa_file_cache_ready))}
      ${metricHtml('File errors', formatCount(counters.pwa_file_cache_error))}
      ${metricHtml('Evicted entries', formatCount(counters.pwa_eviction_count))}
      ${metricHtml('Evicted data', formatBytes(counters.pwa_eviction_bytes))}
      ${metricHtml('Quota usage samples', formatCount(counters.pwa_quota_usage))}
      ${metricHtml('Quota checks / errors', ratio(counters.pwa_quota_estimate, counters.pwa_quota_error))}
    </div>
  </div>`;
}

function resilienceHtml(metrics: PwaCacheMetricsSnapshot): string {
  const counters = metrics.counters;
  const wait = metrics.requestWait;
  return `<div class="settings-cache-diagnostics__section">
    <h4>Requests and recovery</h4>
    <div class="settings-cache-diagnostics__grid">
      ${metricHtml('Pending waits', formatCount(wait.pendingCount))}
      ${metricHtml('Oldest pending', formatOptionalDuration(wait.oldestPendingMs))}
      ${metricHtml('Average wait', formatDuration(wait.averageDurationMs))}
      ${metricHtml('Longest wait', formatDuration(wait.maxDurationMs))}
      ${metricHtml('Resolved / cancelled', ratio(counters.pwa_request_wait_resolved, counters.pwa_request_wait_cancelled))}
      ${metricHtml('Retry attempts', formatCount(counters.pwa_request_retry_attempt))}
      ${metricHtml('Worker installs / updates', ratio(counters.pwa_sw_install, counters.pwa_sw_update))}
      ${metricHtml('Worker recoveries / errors', ratio(counters.pwa_sw_recovery, counters.pwa_sw_error))}
      ${metricHtml('Static cache errors', formatCount(counters.pwa_static_cache_error))}
    </div>
  </div>`;
}

function metricHtml(label: string, value: string): string {
  return `<div class="settings-cache-diagnostics__metric">
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(value)}</strong>
  </div>`;
}

function formatOptionalBytes(value: number | null): string {
  return value === null ? 'Unavailable' : formatBytes(value);
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const unitIndex = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  const amount = value / (1024 ** unitIndex);
  return `${amount >= 10 || unitIndex === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unitIndex]}`;
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

function ratio(first: number, second: number): string {
  return `${formatCount(first)} / ${formatCount(second)}`;
}

function formatOptionalDuration(value: number | null): string {
  return value === null ? 'None' : formatDuration(value);
}

function formatDuration(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 ms';
  return value < 1_000 ? `${Math.round(value)} ms` : `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

function formatTimestamp(value: number): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : 'this session';
}
