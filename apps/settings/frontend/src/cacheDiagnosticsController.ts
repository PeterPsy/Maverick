import {
  clearParentPwaCache,
  requestParentPwaCacheDashboard,
  type PwaCacheDashboard,
} from '@maverick/pwa-cache';
import type { SettingsNotice } from './notice';

export type CacheDiagnosticsViewState = {
  confirmClear: boolean;
  dashboard: PwaCacheDashboard | null;
  error: string;
  isClearing: boolean;
  isLoading: boolean;
};

export function createCacheDiagnosticsController(context: {
  render: () => void;
  setNotice: (notice: SettingsNotice | null) => void;
}) {
  let dashboard: PwaCacheDashboard | null = null;
  let error = '';
  let isClearing = false;
  let isLoading = false;
  let confirmClear = false;

  async function ensureLoaded(force = false): Promise<void> {
    if (isLoading || (!force && dashboard)) {
      return;
    }
    isLoading = true;
    error = '';
    context.render();
    try {
      dashboard = await requestParentPwaCacheDashboard();
      if (!dashboard) throw new Error('Cache diagnostics are unavailable outside the Maverick shell.');
    } catch (loadError) {
      error = errorMessage(loadError, 'Unable to inspect this browser cache.');
    } finally {
      isLoading = false;
      context.render();
    }
  }

  async function clear(): Promise<void> {
    if (!confirmClear) {
      confirmClear = true;
      context.setNotice({ tone: 'info', message: 'Press Clear cache again to confirm removal from this browser.' });
      context.render();
      return;
    }
    isClearing = true;
    error = '';
    context.render();
    try {
      const result = await clearParentPwaCache();
      if (!result) throw new Error('Cache cleanup is unavailable outside the Maverick shell.');
      const { cleanup } = result;
      if (cleanup.status !== 'complete' || cleanup.pendingCleanupCount > 0) {
        throw new Error('Cache cleanup is still pending. Persistent cache reads remain blocked; retry Clear cache.');
      }
      confirmClear = false;
      dashboard = result.dashboard;
      context.setNotice({
        tone: 'success',
        message: cleanup.removed === 1 ? '1 cached entry removed.' : `${cleanup.removed} cached entries removed.`
      });
    } catch (clearError) {
      error = errorMessage(clearError, 'Unable to clear this browser cache.');
      context.setNotice({ tone: 'error', message: error });
    } finally {
      isClearing = false;
      context.render();
    }
  }

  function cancelClear(): void {
    if (!confirmClear) return;
    confirmClear = false;
    context.setNotice(null);
    context.render();
  }

  function viewState(): CacheDiagnosticsViewState {
    return { confirmClear, dashboard, error, isClearing, isLoading };
  }

  return { cancelClear, clear, ensureLoaded, viewState };
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
