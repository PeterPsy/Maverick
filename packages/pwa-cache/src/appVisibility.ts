import { isExactLoopinoParentMessage } from './dataCacheBrokerProtocol';

let shellVisible = true;
type VisibilityOptions = { requireOnline?: boolean };
const listeners = new Set<{ notify: (visible: boolean) => void; options: VisibilityOptions; previous: boolean }>();
let teardown: (() => void) | null = null;

export function loopinoAppIsVisible(options: VisibilityOptions = {}): boolean {
  return shellVisible && !globalThis.document?.hidden
    && (options.requireOnline === false || globalThis.navigator?.onLine !== false);
}

/** Shared shell/document/connectivity intersection; no timers or network work. */
export function observeLoopinoVisibility(listener: (visible: boolean) => void, options: VisibilityOptions = {}): () => void {
  if (typeof window === 'undefined') { listener(true); return () => {}; }
  const subscriber = { notify: listener, options, previous: loopinoAppIsVisible(options) };
  listeners.add(subscriber);
  if (!teardown) {
    const update = () => {
      for (const subscriber of listeners) {
        const next = loopinoAppIsVisible(subscriber.options);
        if (next === subscriber.previous) continue;
        subscriber.previous = next;
        subscriber.notify(next);
      }
    };
    const message = (event: MessageEvent) => {
      if (!isExactLoopinoParentMessage(event) || event.data?.type !== 'loopino.app.visibility-changed'
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
  listener(subscriber.previous);
  return () => {
    listeners.delete(subscriber);
    if (!listeners.size) { teardown?.(); teardown = null; shellVisible = true; }
  };
}
