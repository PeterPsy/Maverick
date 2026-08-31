import type { CacheDiagnostics } from '@maverick/pwa-cache';
import type { CacheDiagnosticsViewState } from './cacheDiagnosticsController';
import { escapeHtml } from './html';

export function cacheDiagnosticsPageHtml(state: CacheDiagnosticsViewState): string {
  const { confirmClear, diagnostics, error, isClearing, isLoading } = state;
  const actionLabel = isClearing ? 'Clearing…' : confirmClear ? 'Confirm clear cache' : 'Clear cache';
  return `<section class="settings-card settings-cache-diagnostics" aria-busy="${isLoading || isClearing}">
    <div class="settings-heading">
      <div>
        <span class="settings-kicker">This browser</span>
        <h3>Maverick data cache</h3>
      </div>
      <span class="settings-pill settings-pill-muted">Disposable</span>
    </div>
    <p class="settings-card-copy">Inspect aggregate structured-cache usage for this browser container. Cached entries are rebuildable and never authorize server actions.</p>
    ${error ? `<div class="settings-cache-diagnostics__error" role="alert">${escapeHtml(error)}</div>` : ''}
    ${diagnosticsHtml(diagnostics, isLoading)}
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
    <p class="settings-cache-diagnostics__note">Clear cache removes only Maverick's structured browser data cache. It does not delete server data or indiscriminately clear this origin.</p>
  </section>`;
}

function diagnosticsHtml(diagnostics: CacheDiagnostics | null, isLoading: boolean): string {
  if (!diagnostics || isLoading) {
    return `<div class="settings-cache-diagnostics__grid" aria-label="Loading cache diagnostics">
      ${metricHtml('Cache data', '—')}
      ${metricHtml('Entries', '—')}
      ${metricHtml('Origin usage', '—')}
      ${metricHtml('Origin quota', '—')}
    </div>`;
  }
  return `<div class="settings-cache-diagnostics__grid">
    ${metricHtml('Cache data', formatBytes(diagnostics.cacheBytes))}
    ${metricHtml('Entries', diagnostics.entryCount.toLocaleString())}
    ${metricHtml('Origin usage', formatOptionalBytes(diagnostics.originUsageBytes))}
    ${metricHtml('Origin quota', formatOptionalBytes(diagnostics.originQuotaBytes))}
    ${metricHtml('Backend', diagnostics.backend === 'indexeddb' ? 'IndexedDB' : 'Memory fallback')}
    ${metricHtml('Pending cleanup', diagnostics.pendingCleanupCount.toLocaleString())}
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
