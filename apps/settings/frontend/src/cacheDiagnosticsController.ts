import { clearPwaDataCache, readPwaCacheDiagnostics, type CacheDiagnostics } from '@maverick/pwa-cache';
import type { SettingsNotice } from './notice';

export type CacheDiagnosticsViewState = {
  confirmClear: boolean;
  diagnostics: CacheDiagnostics | null;
  error: string;
  isClearing: boolean;
  isLoading: boolean;
};

export function createCacheDiagnosticsController(context: {
  render: () => void;
  setNotice: (notice: SettingsNotice | null) => void;
}) {
  let diagnostics: CacheDiagnostics | null = null;
  let error = '';
  let isClearing = false;
  let isLoading = false;
  let confirmClear = false;

  async function ensureLoaded(force = false): Promise<void> {
    if (isLoading || (!force && diagnostics)) {
      return;
    }
    isLoading = true;
    error = '';
    context.render();
    try {
      diagnostics = await readPwaCacheDiagnostics();
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
      const removed = await clearPwaDataCache();
      confirmClear = false;
      diagnostics = await readPwaCacheDiagnostics();
      context.setNotice({
        tone: 'success',
        message: removed === 1 ? '1 cached entry removed.' : `${removed} cached entries removed.`
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
    return { confirmClear, diagnostics, error, isClearing, isLoading };
  }

  return { cancelClear, clear, ensureLoaded, viewState };
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
