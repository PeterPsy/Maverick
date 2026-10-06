import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reportShellAuthorizationFailure, resetShellAuthorizationChecks } from "../src/shellAuthorization";
import { shellCacheLifecycle, subscribeShellAuthorizationRevocation } from "../src/pwaCacheRuntime";

describe("platform session confirmation", () => {
  const revoked = vi.fn();
  let unsubscribe: () => void;
  beforeEach(() => {
    resetShellAuthorizationChecks();
    revoked.mockReset();
    unsubscribe = subscribeShellAuthorizationRevocation(revoked);
    vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockResolvedValue({ status: "complete", removed: 0, pendingCleanupCount: 0 });
  });
  afterEach(() => { unsubscribe(); vi.restoreAllMocks(); });

  it.each([401, 403] as const)("retains login after resource HTTP %i when the platform session is live", async (status) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ authenticated: true })));
    await reportShellAuthorizationFailure(status, "/api/apps/senses/backend");
    expect(revoked).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith("/api/session", expect.objectContaining({ cache: "no-store", credentials: "same-origin" }));
  });

  it.each([401, 200])("revokes only after confirmed platform loss (%i)", async (status) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ authenticated: false }), { status }));
    await reportShellAuthorizationFailure(403);
    expect(revoked).toHaveBeenCalledWith(401);
  });

  it.each([403, 500, 503])("keeps recovery credentials when confirmation returns HTTP %i", async (status) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status }));
    await reportShellAuthorizationFailure(401);
    expect(revoked).not.toHaveBeenCalled();
  });

  it("coalesces confirmations and ignores a stale response after a new login", async () => {
    let resolve!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>(done => { resolve = done; }));
    const first = reportShellAuthorizationFailure(401);
    const second = reportShellAuthorizationFailure(403);
    expect(first).toBe(second);
    expect(fetch).toHaveBeenCalledOnce();
    resetShellAuthorizationChecks();
    resolve(new Response(JSON.stringify({ authenticated: false })));
    await first;
    expect(revoked).not.toHaveBeenCalled();
  });

  it("does not log out when offline or when session access is forbidden", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    await reportShellAuthorizationFailure(401);
    await reportShellAuthorizationFailure(403, "/api/session");
    expect(revoked).not.toHaveBeenCalled();
  });
});
