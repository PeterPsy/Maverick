import { useCallback, useEffect, useRef } from "react";
import { maverickAppIsVisible, observeMaverickVisibility } from "@maverick/pwa-cache";

// Read callbacks own their UI errors and ignore results after their signal aborts.
// Mutations must never use this scheduler: hiding an app cannot cancel a send.
export function useVisiblePolling(
  read: (signal: AbortSignal) => Promise<boolean | void>,
  interval: number,
  enabled = true,
) {
  const runner = useRef<() => Promise<void>>(async () => {});
  const refresh = useCallback(() => runner.current(), []);
  useEffect(() => {
    let disposed = false;
    let pending: Promise<void> | undefined;
    let controller: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let queued = false;
    let failures = 0;
    const visible = () => !disposed && enabled && maverickAppIsVisible();
    function run(resetDelay = false): Promise<void> {
      if (!visible()) return Promise.resolve();
      if (resetDelay) failures = 0;
      clearTimeout(timer);
      if (pending) {
        queued = true;
        return pending;
      }
      pending = (async () => {
        do {
          queued = false;
          controller = new AbortController();
          const result = await read(controller.signal);
          failures = result === false ? failures + 1 : 0;
        } while (queued && visible());
      })().finally(() => {
        pending = undefined;
        if (visible()) timer = setTimeout(() => { void run(); }, Math.min(interval * 2 ** Math.min(failures, 6), 60000));
      });
      return pending;
    }
    runner.current = () => run(true);
    const stop = observeMaverickVisibility((isVisible) => {
      if (isVisible) void run(true);
      else {
        queued = false;
        clearTimeout(timer);
        controller?.abort();
      }
    });
    return () => {
      disposed = true;
      stop();
      clearTimeout(timer);
      controller?.abort();
    };
  }, [read, interval, enabled]);
  return refresh;
}
