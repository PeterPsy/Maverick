import { revokeShellAuthorization, subscribeShellAuthorizationRevocation } from "./pwaCacheRuntime";

let epoch = 0;
let pending: Promise<void> | null = null;
subscribeShellAuthorizationRevocation(() => { epoch += 1; });

/** Fence late failures from a previous login, logout, or workspace. */
export function resetShellAuthorizationChecks(): void {
  epoch += 1;
  pending = null;
}

export function shellAuthorizationEpoch(): number { return epoch; }

/** Resource/isolated-frame denial is not proof that the platform login ended. */
export function reportShellAuthorizationFailure(status: 401 | 403, endpoint?: string): Promise<void> {
  if (endpoint === "/api/session") {
    return status === 401 ? revokeShellAuthorization(401) : Promise.resolve();
  }
  if (pending) return pending;
  const generation = epoch;
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), 5_000);
  const check = (async () => {
    try {
      const response = await fetch("/api/session", {
        cache: "no-store", credentials: "same-origin", signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (generation !== epoch) return;
      if (response.status === 401) {
        await revokeShellAuthorization(401);
      } else if (response.ok) {
        const payload = await response.json() as { authenticated?: unknown };
        if (generation === epoch && payload.authenticated === false) await revokeShellAuthorization(401);
      }
    } catch {
      // Offline, server errors and invalid responses cannot establish logout.
    } finally {
      globalThis.clearTimeout(timeout);
    }
  })();
  pending = check;
  void check.finally(() => { if (pending === check) pending = null; });
  return check;
}
