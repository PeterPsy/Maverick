import { withCrossClientLock } from "./cacheBus";

type Flight<T> = {
  consumers: number;
  controller: AbortController;
  promise: Promise<T>;
};

const inFlight = new Map<string, Flight<unknown>>();

export function runSingleFlight<T>(
  key: string,
  operation: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) return Promise.reject(cancellation(signal));
  let flight = inFlight.get(key) as Flight<T> | undefined;
  if (!flight) {
    const controller = new AbortController();
    const promise = withCrossClientLock(key, () => {
      if (controller.signal.aborted) throw cancellation(controller.signal);
      // Release the lock on cancellation even when a loader ignores its signal.
      // Publication still has to check this shared signal before committing.
      return cancellable(operation(controller.signal), controller.signal);
    }, { signal: controller.signal }).finally(() => {
      if (inFlight.get(key)?.controller === controller) inFlight.delete(key);
    });
    flight = { consumers: 0, controller, promise };
    inFlight.set(key, flight);
  }
  const shared = flight;
  shared.consumers += 1;
  return cancellable(shared.promise, signal).finally(() => {
    shared.consumers -= 1;
    if (shared.consumers === 0 && inFlight.get(key) === shared) {
      inFlight.delete(key);
      shared.controller.abort(new DOMException("No active cache readers remain.", "AbortError"));
    }
  });
}

function cancellable<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    const abort = () => reject(cancellation(signal));
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

function cancellation(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("Cache read cancelled.", "AbortError");
}
