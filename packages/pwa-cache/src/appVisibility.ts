import { isExactMaverickParentMessage } from './dataCacheBrokerProtocol';

let shellVisible = true;
const listeners = new Set<(visible: boolean) => void>();
let teardown: (() => void) | null = null;

export function maverickAppIsVisible(): boolean {
  return shellVisible && !globalThis.document?.hidden && globalThis.navigator?.onLine !== false;
}

/** Shared shell/document/connectivity intersection; no timers or network work. */
export function observeMaverickVisibility(listener: (visible: boolean) => void): () => void {
  if (typeof window === 'undefined') { listener(true); return () => {}; }
  listeners.add(listener);
  if (!teardown) {
    let previous = maverickAppIsVisible();
    const update = () => {
      const next = maverickAppIsVisible();
      if (next === previous) return;
      previous = next;
      for (const subscriber of listeners) subscriber(next);
    };
    const message = (event: MessageEvent) => {
      if (!isExactMaverickParentMessage(event) || event.data?.type !== 'maverick.app.visibility-changed'
          || typeof event.data.visible !== 'boolean') return;
      shellVisible = event.data.visible;
      update();
    };
    window.addEventListener?.('message', message);
    window.addEventListener?.('online', update);
    window.addEventListener?.('offline', update);
    globalThis.document?.addEventListener('visibilitychange', update);
    teardown = () => {
      window.removeEventListener?.('message', message);
      window.removeEventListener?.('online', update);
      window.removeEventListener?.('offline', update);
      globalThis.document?.removeEventListener('visibilitychange', update);
    };
  }
  listener(maverickAppIsVisible());
  return () => {
    listeners.delete(listener);
    if (!listeners.size) { teardown?.(); teardown = null; shellVisible = true; }
  };
}
