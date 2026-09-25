import { describe, expect, it } from 'vitest';
import type { ProviderSubscriptionUsage } from './adminApi';
import { providerUsageSummary } from './providerUsageSummary';

function state(items: ProviderSubscriptionUsage[]) {
  return {
    isLoadingProviderUsage: false,
    providerUsageError: '',
    providerUsageItems: items,
  };
}

describe('provider usage summaries', () => {
  it('shows the Codex limit window and renewal countdown', () => {
    const summary = providerUsageSummary('codex', state([{
      provider_id: 'codex', provider_label: 'Codex', available: true,
      fetched_at: '2026-09-25T12:00:00Z', plan_type: 'pro', unavailable_reason: null,
      credits_balance: 0, credits_unlimited: false,
      limits: [{
        limit_id: 'codex', label: 'Codex', metered_feature: null, limit_reached: false,
        primary_window: {
          used_percent: 4, limit_window_seconds: 604800,
          reset_after_seconds: 467405, reset_at_epoch_seconds: null,
        },
        secondary_window: null,
      }],
    }]), Date.parse('2026-09-25T12:00:00Z'));

    expect(summary).toBe('1w window: 4% used · 96% remaining before limit · resets in 5d 9h');
  });

  it('keeps Antigravity model groups and both quota windows visible', () => {
    const summary = providerUsageSummary('antigravity-cli', state([{
      provider_id: 'antigravity-cli', provider_label: 'Antigravity', available: true,
      fetched_at: '2026-09-25T12:00:00Z', plan_type: null, unavailable_reason: null,
      credits_balance: null, credits_unlimited: false,
      limits: [{
        limit_id: 'antigravity:gemini', label: 'Gemini Models', metered_feature: null,
        limit_reached: false,
        primary_window: {
          used_percent: 14, limit_window_seconds: 604800,
          reset_after_seconds: null, reset_at_epoch_seconds: 1790337600,
        },
        secondary_window: {
          used_percent: 0, limit_window_seconds: 18000,
          reset_after_seconds: 10800, reset_at_epoch_seconds: null,
        },
      }, {
        limit_id: 'antigravity:third-party', label: 'Claude and GPT models', metered_feature: null,
        limit_reached: false,
        primary_window: {
          used_percent: 0, limit_window_seconds: 604800,
          reset_after_seconds: 604800, reset_at_epoch_seconds: null,
        },
        secondary_window: null,
      }],
    }]), Date.parse('2026-09-25T12:00:00Z'));

    expect(summary).toContain('Gemini Models — 1w window: 14% used');
    expect(summary).toContain('5h window: 0% used · 100% remaining before limit · resets in 3h');
    expect(summary).toContain('Claude and GPT models — 1w window: 0% used');
  });
});
