import { observeMaverickVisibility } from '@maverick/pwa-cache';
import { requestOpenDesignBootstrapStatus, SidecarLaunchError } from './api';
import type { SidecarLaunch } from './types';

/** Pause only confirmation reads; a redeemed one-shot launch remains intact. */
export function observeBootstrapConfirmation(appId: string, launch: SidecarLaunch, signal: AbortSignal,
  onReady: () => void, onError: (error: unknown) => void): () => void {
  const deadline = Date.now() + launch.expires_in_seconds * 1000;
  let stopped = false;
  let request: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopVisibility = () => {};

  function suspend() {
    clearTimeout(timer);
    timer = undefined;
    request?.abort();
    request = null;
  }
  function stop() {
    if (stopped) return;
    stopped = true;
    suspend();
    stopVisibility();
    signal.removeEventListener('abort', stop);
  }
  async function poll() {
    if (stopped) return;
    const current = new AbortController();
    request = current;
    try {
      const status = await requestOpenDesignBootstrapStatus(appId, launch, current.signal);
      if (current.signal.aborted || stopped) return;
      if (status === 'ready') {
        stop();
        onReady();
      } else {
        if (Date.now() >= deadline) throw new SidecarLaunchError('sidecar_bootstrap_unconfirmed', 408);
        timer = setTimeout(poll, 200);
      }
    } catch (error) {
      if (current.signal.aborted || stopped) return;
      stop();
      onError(error);
    } finally {
      if (request === current) request = null;
    }
  }
  if (signal.aborted) return stop;
  signal.addEventListener('abort', stop, { once: true });
  stopVisibility = observeMaverickVisibility(visible => {
    if (visible) void poll();
    else suspend();
  });
  return stop;
}
