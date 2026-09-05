// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PwaCacheDashboard, PwaCacheMetricsSnapshot } from '@maverick/pwa-cache';
import { bindCacheDiagnosticsEvents } from './bindEvents';
import { createCacheDiagnosticsController } from './cacheDiagnosticsController';
import { cacheDiagnosticsPageHtml } from './cacheDiagnosticsPage';
import type { SettingsNotice } from './notice';

const parentProtocol = vi.hoisted(() => ({
  clear: vi.fn(),
  diagnostics: vi.fn(),
}));

vi.mock('@maverick/pwa-cache', () => ({
  clearParentPwaCache: parentProtocol.clear,
  requestParentPwaCacheDashboard: parentProtocol.diagnostics,
}));

describe('Settings cache diagnostics flow', () => {
  beforeEach(() => {
    parentProtocol.clear.mockReset();
    parentProtocol.diagnostics.mockReset();
    document.body.innerHTML = '';
  });

  afterEach(() => vi.restoreAllMocks());

  it('loads, force-refreshes, confirms, and completes a clear through the rendered controls', async () => {
    const initial = dashboard(4);
    const refreshed = dashboard(7);
    const cleared = dashboard(0);
    parentProtocol.diagnostics.mockResolvedValueOnce(initial).mockResolvedValueOnce(refreshed);
    parentProtocol.clear.mockResolvedValue({
      cleanup: { pendingCleanupCount: 0, removed: 7, status: 'complete' },
      dashboard: cleared,
    });
    const notices: Array<SettingsNotice | null> = [];
    let controller: ReturnType<typeof createCacheDiagnosticsController>;
    const render = () => {
      document.body.innerHTML = cacheDiagnosticsPageHtml(controller.viewState());
      bindCacheDiagnosticsEvents({ cacheDiagnosticsController: controller, showError: vi.fn() });
    };
    controller = createCacheDiagnosticsController({ render, setNotice: (notice) => notices.push(notice) });

    render();
    await controller.ensureLoaded();
    expect(document.body.textContent).toContain('4');

    document.querySelector<HTMLButtonElement>('#refresh-pwa-cache')?.click();
    await vi.waitFor(() => expect(parentProtocol.diagnostics).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(document.body.textContent).toContain('7'));

    document.querySelector<HTMLButtonElement>('#clear-pwa-cache')?.click();
    expect(parentProtocol.clear).not.toHaveBeenCalled();
    expect(document.querySelector('#clear-pwa-cache')?.textContent).toContain('Confirm clear cache');

    document.querySelector<HTMLButtonElement>('#clear-pwa-cache')?.click();
    await vi.waitFor(() => expect(parentProtocol.clear).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(controller.viewState().isClearing).toBe(false));
    expect(controller.viewState().confirmClear).toBe(false);
    expect(notices.at(-1)).toEqual({ tone: 'success', message: '7 cached entries removed.' });
  });

  it('keeps confirmation available and surfaces durable pending cleanup', async () => {
    parentProtocol.diagnostics.mockResolvedValue(dashboard(2));
    parentProtocol.clear.mockResolvedValue({
      cleanup: { pendingCleanupCount: 1, removed: 1, status: 'pending' },
      dashboard: dashboard(1),
    });
    const notices: Array<SettingsNotice | null> = [];
    let controller: ReturnType<typeof createCacheDiagnosticsController>;
    const render = () => {
      document.body.innerHTML = cacheDiagnosticsPageHtml(controller.viewState());
      bindCacheDiagnosticsEvents({ cacheDiagnosticsController: controller, showError: vi.fn() });
    };
    controller = createCacheDiagnosticsController({ render, setNotice: (notice) => notices.push(notice) });

    await controller.ensureLoaded();
    document.querySelector<HTMLButtonElement>('#clear-pwa-cache')?.click();
    document.querySelector<HTMLButtonElement>('#clear-pwa-cache')?.click();

    await vi.waitFor(() => expect(controller.viewState().isClearing).toBe(false));
    expect(controller.viewState().confirmClear).toBe(true);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('still pending');
    expect(notices.at(-1)?.tone).toBe('error');
  });
});

function dashboard(entryCount: number): PwaCacheDashboard {
  const counters = new Proxy({}, { get: () => 0 }) as PwaCacheMetricsSnapshot['counters'];
  return {
    diagnostics: {
      backend: 'indexeddb',
      cacheBytes: entryCount * 100,
      entryCount,
      fileCacheAvailable: true,
      fileCacheBytes: 0,
      fileCacheEntryCount: 0,
      originQuotaBytes: 10_000,
      originUsageBytes: entryCount * 100,
      pendingCleanupCount: 0,
      structuredCacheBytes: entryCount * 100,
      structuredEntryCount: entryCount,
    },
    metrics: {
      schema: 'maverick.pwa-cache-metrics.v1',
      counters,
      quota: { lastEstimatedAt: 1, quotaBytes: 10_000, supported: true, usageBytes: entryCount * 100 },
      requestWait: {
        averageDurationMs: 0,
        durationObservations: 0,
        maxDurationMs: 0,
        oldestPendingMs: null,
        pendingCount: 0,
        totalDurationMs: 0,
      },
      updatedAt: 1,
      windowStartedAt: 1,
    },
  };
}
