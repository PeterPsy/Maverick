import { withCrossClientLock } from "./cacheBus";

const inFlight = new Map<string, Promise<unknown>>();

export function runSingleFlight<T>(key: string, operation: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key) as Promise<T> | undefined;
  if (existing) {
    return existing;
  }
  const pending = withCrossClientLock(key, operation).finally(() => {
    if (inFlight.get(key) === pending) {
      inFlight.delete(key);
    }
  });
  inFlight.set(key, pending);
  return pending;
}
