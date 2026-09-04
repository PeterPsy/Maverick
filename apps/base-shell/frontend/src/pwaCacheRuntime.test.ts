import { describe, expect, it, vi } from "vitest";
import {
  revokeShellAuthorization,
  shellCacheLifecycle,
  subscribeShellAuthorizationRevocation,
} from "./pwaCacheRuntime";

describe("Base Shell authorization revocation channel", () => {
  it("notifies synchronously and coalesces cleanup for one revocation wave", async () => {
    const pendingCleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.authorizationFailure>>>();
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockReturnValue(pendingCleanup.promise);
    const listener = vi.fn();
    const unsubscribe = subscribeShellAuthorizationRevocation(listener);

    const first = revokeShellAuthorization(401);
    const duplicate = revokeShellAuthorization(403);

    expect(first).toBe(duplicate);
    expect(listener).toHaveBeenCalledOnce();
    expect(listener).toHaveBeenCalledWith(401);
    expect(cleanup).toHaveBeenCalledOnce();

    pendingCleanup.resolve({ pendingCleanupCount: 0, removed: 1, status: "complete" });
    await first;
    unsubscribe();
    vi.restoreAllMocks();
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
