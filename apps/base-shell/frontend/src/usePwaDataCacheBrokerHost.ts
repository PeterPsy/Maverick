import { useLayoutEffect, useRef } from "react";
import { clampPrivateAccessLease } from "@maverick/pwa-cache";
import type { AppRegistryItem } from "./api";
import type { MaverickFrameScope } from "./iframePolicy";
import { PwaDataCacheBroker } from "./pwaDataCacheBroker";

type AuthenticatedCachePrincipal = {
  sessionExpiresAt: string;
  userId: string;
  workspaceId: string;
};

export function usePwaDataCacheBrokerHost({
  appRegistry,
  frameScope,
  principal,
}: {
  appRegistry: readonly AppRegistryItem[];
  frameScope: MaverickFrameScope | null;
  principal: AuthenticatedCachePrincipal | null;
}): void {
  const enabledAppIdsRef = useRef<ReadonlySet<string>>(new Set());
  enabledAppIdsRef.current = new Set(
    appRegistry.filter((app) => app.data_cache_enabled).map((app) => app.app_id),
  );

  useLayoutEffect(() => {
    if (!principal || !frameScope || frameScope.workspaceId !== principal.workspaceId) return undefined;
    const sessionExpiry = Date.parse(principal.sessionExpiresAt);
    const accessLease = Number.isFinite(sessionExpiry)
      ? clampPrivateAccessLease(sessionExpiry) ?? undefined
      : undefined;
    const broker = new PwaDataCacheBroker({
      accessLease,
      frameScope,
      principal: {
        userId: principal.userId,
        workspaceId: principal.workspaceId,
      },
    });
    const handleMessage = (event: MessageEvent) => {
      if (broker.handleWindowMessage(event, enabledAppIdsRef.current)) return;
      broker.handleDataChangedMessage(event);
    };
    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
      broker.dispose();
    };
  }, [
    frameScope?.sessionGeneration,
    frameScope?.workspaceId,
    principal?.sessionExpiresAt,
    principal?.userId,
    principal?.workspaceId,
  ]);
}
