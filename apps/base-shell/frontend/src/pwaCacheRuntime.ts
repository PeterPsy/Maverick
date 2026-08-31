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
