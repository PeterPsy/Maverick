import { describe, expect, it, vi } from "vitest";
import {
  revokeShellAuthorization,
  shellCacheLifecycle,
  subscribeShellAuthorizationRevocation,
} from "./pwaCacheRuntime";

describe("Base Shell authorization revocation channel", () => {
  it("repeats synchronous notifications while coalescing cleanup for one revocation wave", async () => {
    const pendingCleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.authorizationFailure>>>();
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockReturnValue(pendingCleanup.promise);
    const listener = vi.fn();
    const unsubscribe = subscribeShellAuthorizationRevocation(listener);

    const first = revokeShellAuthorization(401);
    const duplicate = revokeShellAuthorization(403);

    try {
      expect(first).toBe(duplicate);
      expect(listener.mock.calls).toEqual([[401], [403]]);
      expect(cleanup).toHaveBeenCalledOnce();
    } finally {
      pendingCleanup.resolve({ pendingCleanupCount: 0, removed: 1, status: "complete" });
      await first;
      unsubscribe();
      vi.restoreAllMocks();
    }
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}
