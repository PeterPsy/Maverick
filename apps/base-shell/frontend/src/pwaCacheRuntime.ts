import {
  RetryCoordinator,
  clampPrivateAccessLease,
  createCacheLifecycleController,
  type CacheLifecyclePrincipal,
} from "@maverick/pwa-cache";
import type { SessionPayload } from "./api";

export const shellRetryCoordinator = new RetryCoordinator();
export const shellCacheLifecycle = createCacheLifecycleController({
  retryCoordinator: shellRetryCoordinator,
});

export type ShellAuthorizationStatus = 401 | 403;
type ShellAuthorizationRevocationListener = (status: ShellAuthorizationStatus) => void;

const authorizationRevocationListeners = new Set<ShellAuthorizationRevocationListener>();
let authorizationRevocationInFlight: Promise<void> | null = null;

export function subscribeShellAuthorizationRevocation(
  listener: ShellAuthorizationRevocationListener,
): () => void {
  authorizationRevocationListeners.add(listener);
  return () => authorizationRevocationListeners.delete(listener);
}

export function revokeShellAuthorization(status: ShellAuthorizationStatus): Promise<void> {
  const revocation = authorizationRevocationInFlight ?? startAuthorizationRevocationCleanup();

  for (const listener of [...authorizationRevocationListeners]) {
    try {
      listener(status);
    } catch {
      // UI teardown is best-effort per listener; cache cleanup remains authoritative.
    }
  }
  return revocation;
}

function startAuthorizationRevocationCleanup(): Promise<void> {
  let cleanup: Promise<unknown>;
  try {
    cleanup = shellCacheLifecycle.authorizationFailure();
  } catch {
    cleanup = Promise.resolve();
  }
  const revocation = cleanup
    .catch(() => undefined)
    .then(() => undefined)
    .finally(() => {
      if (authorizationRevocationInFlight === revocation) {
        authorizationRevocationInFlight = null;
      }
    });
  authorizationRevocationInFlight = revocation;
  return revocation;
}

export function initializeShellPwaCacheRuntime(): void {
  shellRetryCoordinator.start();
  void shellCacheLifecycle.initialize().catch(() => undefined);
}

export function shellCachePrincipal(
  session: Extract<SessionPayload, { authenticated: true }>,
): CacheLifecyclePrincipal {
  const sessionExpiresAt = Date.parse(session.expires_at);
  return {
    appId: "base-shell",
    userId: session.user.user_id,
    workspaceId: session.workspace_id,
    ...(Number.isFinite(sessionExpiresAt)
      ? { accessLease: clampPrivateAccessLease(sessionExpiresAt) ?? undefined }
      : {}),
  };
}

export function runShellRead<T>(
  key: string,
  operation: (signal: AbortSignal) => Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  return shellRetryCoordinator.run({
    key,
    method: "GET",
    operation: ({ signal: retrySignal }) => operation(retrySignal),
    signal,
  });
}
