import type { SettingsPanelState } from './settingsDrafts';
import { escapeHtml } from './html';
import { usageHistoryTimeRange } from './usageHistoryFilters';
import { providerUsageSummary } from './providerUsageSummary';

export function usageHistoryCardHtml(state: SettingsPanelState) {
  const refreshIcon = state.isLoadingUsageHistory ? 'sync' : 'refresh';
  const timeRange = usageHistoryTimeRange(state.usageHistoryFilters.timeRange);
  const chartTitle = timeRange.resolution === 'hour' ? 'Hourly consumption' : 'Daily consumption';
  return `<section class="settings-card settings-platform settings-usage-history-card" aria-labelledby="settings-usage-history-title">
    <div class="settings-heading settings-platform-heading settings-usage-history-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">monitoring</span>
      <div>
        <p class="settings-kicker">Workspace metering</p>
        <h2 id="settings-usage-history-title">Token usage history</h2>
      </div>
      <button type="button" class="settings-secondary settings-provider-usage-refresh" id="settings-refresh-usage-history" ${state.isLoadingUsageHistory ? 'disabled' : ''}>
        <span class="material-symbols-rounded ${state.isLoadingUsageHistory ? 'is-spinning' : ''}" aria-hidden="true">${refreshIcon}</span>
        Refresh
      </button>
    </div>
    <p class="settings-card-copy">Usage across root and delegated runtime sessions. The chart defaults to non-cached tokens; use the filters to inspect processed totals, cache, providers, models, and time ranges.</p>
    ${state.usageHistoryError ? `<p class="settings-inline-error" role="alert">${escapeHtml(state.usageHistoryError)}</p>` : ''}
    <div class="settings-usage-history-filters" data-usage-history-filters aria-label="Token history filters"></div>
    <article class="settings-usage-history-panel">
      <div>
        <p class="settings-kicker">Last ${escapeHtml(timeRange.label)}</p>
        <h3>${chartTitle}</h3>
      </div>
      <div data-usage-history-chart aria-live="polite"></div>
    </article>
  </section>`;
}


export function usagePageHtml(state: SettingsPanelState) {
  return `<section class="settings-card"><div class="settings-heading"><h2>Provider subscriptions</h2></div>
    ${state.providerUsageError ? `<p role="alert">${escapeHtml(state.providerUsageError)}</p>` : ''}
    ${state.isLoadingProviderUsage ? '<p role="status">Loading subscription usage…</p>' : ''}
    ${state.providerUsageItems.map(item => `<article class="settings-subscription-row"><strong>${escapeHtml(item.provider_id)}</strong><p>${escapeHtml(providerUsageSummary(item.provider_id, state))}</p></article>`).join('')}
    ${!state.isLoadingProviderUsage && !state.providerUsageItems.length && !state.providerUsageError ? '<p>No subscription limits reported.</p>' : ''}
  </section>${usageHistoryCardHtml(state)}`;
}
