import { describe, expect, it, vi } from "vitest";
import {
  PWA_CACHE_OPERATIONS_ACCEPTED,
  PWA_CACHE_OPERATIONS_REQUEST,
  PWA_CACHE_OPERATIONS_RESULT,
  clearParentPwaCache,
  createPwaCacheMetricsCollector,
  isParentPwaCacheOperationsRequest,
  requestParentPwaCacheDashboard,
} from "../src";

function dashboard() {
  return {
    diagnostics: {
      backend: "indexeddb" as const,
      cacheBytes: 10,
      entryCount: 1,
      fileCacheAvailable: true,
      fileCacheBytes: 6,
      fileCacheEntryCount: 1,
      originQuotaBytes: 1_000,
      originUsageBytes: 100,
      pendingCleanupCount: 0,
      structuredCacheBytes: 4,
      structuredEntryCount: 1,
    },
    metrics: createPwaCacheMetricsCollector({ now: () => 1_000, storage: null }).snapshot(),
  };
}

describe("parent PWA cache operations protocol", () => {
  it("reads aggregate diagnostics through an accepted exact parent channel", async () => {
    const parentWindow = {
      postMessage(message: unknown, origin: string, ports: Transferable[]) {
        expect(origin).toBe("https://maverick.test");
        expect(message).toMatchObject({ action: "diagnostics", type: PWA_CACHE_OPERATIONS_REQUEST });
        const request = message as { request_id: string };
        const port = ports[0] as MessagePort;
        port.postMessage({ app_id: "settings", request_id: request.request_id, type: PWA_CACHE_OPERATIONS_ACCEPTED });
        port.postMessage({
          app_id: "settings",
          dashboard: dashboard(),
          request_id: request.request_id,
          status: "ok",
          type: PWA_CACHE_OPERATIONS_RESULT,
        });
      },
    };

    await expect(requestParentPwaCacheDashboard({
      parentOrigin: "https://maverick.test",
      parentWindow,
    })).resolves.toMatchObject({ diagnostics: { cacheBytes: 10 } });
  });

  it("requires a complete cleanup result for clear", async () => {
    const parentWindow = {
      postMessage(message: unknown, _origin: string, ports: Transferable[]) {
        const request = message as { request_id: string };
        const port = ports[0] as MessagePort;
        port.postMessage({ app_id: "settings", request_id: request.request_id, type: PWA_CACHE_OPERATIONS_ACCEPTED });
        port.postMessage({
          app_id: "settings",
          cleanup: { pendingCleanupCount: 0, removed: 2, status: "complete" },
          dashboard: dashboard(),
          request_id: request.request_id,
          status: "ok",
          type: PWA_CACHE_OPERATIONS_RESULT,
        });
      },
    };

    await expect(clearParentPwaCache({
      parentOrigin: "https://maverick.test",
      parentWindow,
    })).resolves.toMatchObject({ cleanup: { removed: 2 }, dashboard: { diagnostics: { cacheBytes: 10 } } });
  });

  it("times out to unavailable when no shell broker accepts the request", async () => {
    vi.useFakeTimers();
    const pending = requestParentPwaCacheDashboard({
      acceptanceTimeoutMs: 10,
      parentOrigin: "https://maverick.test",
      parentWindow: { postMessage() {} },
    });
    await vi.advanceTimersByTimeAsync(10);
    await expect(pending).resolves.toBeNull();
    vi.useRealTimers();
  });

  it("rejects malformed or non-Settings requests", () => {
    expect(isParentPwaCacheOperationsRequest({
      action: "clear",
      app_id: "settings",
      request_id: "request-one",
      type: PWA_CACHE_OPERATIONS_REQUEST,
    })).toBe(true);
    expect(isParentPwaCacheOperationsRequest({
      action: "clear",
      app_id: "storage",
      request_id: "request-one",
      type: PWA_CACHE_OPERATIONS_REQUEST,
    })).toBe(false);
  });
});
