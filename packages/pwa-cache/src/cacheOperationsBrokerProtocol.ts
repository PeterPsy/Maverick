import {
  PWA_CACHE_COUNTER_METRICS,
  PWA_CACHE_METRICS_SCHEMA,
  type PwaCacheMetricsSnapshot,
} from "./metricsTypes";
import type { CacheCleanupResult, CacheDiagnostics } from "./types";

export const PWA_CACHE_OPERATIONS_REQUEST = "maverick.pwa.cache-operations.request.v1";
export const PWA_CACHE_OPERATIONS_ACCEPTED = "maverick.pwa.cache-operations.accepted.v1";
export const PWA_CACHE_OPERATIONS_RESULT = "maverick.pwa.cache-operations.result.v1";

const DEFAULT_ACCEPTANCE_TIMEOUT_MS = 750;
const DEFAULT_RESULT_TIMEOUT_MS = 10_000;
const MAX_IDENTITY_LENGTH = 256;

export type PwaCacheOperation = "clear" | "diagnostics";

export type PwaCacheDashboard = {
  diagnostics: CacheDiagnostics;
  metrics: PwaCacheMetricsSnapshot;
};

export type PwaCacheClearResult = {
  cleanup: CacheCleanupResult;
  dashboard: PwaCacheDashboard;
};

export type ParentPwaCacheOperationsOptions = {
  acceptanceTimeoutMs?: number;
  createMessageChannel?: () => MessageChannel;
  parentOrigin?: string;
  parentWindow?: ParentMessageWindow;
  resultTimeoutMs?: number;
};

type ParentMessageWindow = {
  postMessage(message: unknown, targetOrigin: string, transfer?: Transferable[]): void;
};

export type ParentPwaCacheOperationsRequestMessage = {
  action: PwaCacheOperation;
  app_id: "settings";
  request_id: string;
  type: typeof PWA_CACHE_OPERATIONS_REQUEST;
};

export type ParentPwaCacheOperationsAcceptedMessage = {
  app_id: "settings";
  request_id: string;
  type: typeof PWA_CACHE_OPERATIONS_ACCEPTED;
};

export type ParentPwaCacheOperationsResultMessage = {
  app_id: "settings";
  cleanup?: CacheCleanupResult;
  dashboard?: PwaCacheDashboard;
  request_id: string;
  status: "error" | "ok" | "unavailable";
  type: typeof PWA_CACHE_OPERATIONS_RESULT;
};

export function requestParentPwaCacheDashboard(
  options: ParentPwaCacheOperationsOptions = {},
): Promise<PwaCacheDashboard | null> {
  return requestParentOperation("diagnostics", options).then((result) => result?.dashboard ?? null);
}

export function clearParentPwaCache(
  options: ParentPwaCacheOperationsOptions = {},
): Promise<PwaCacheClearResult | null> {
  return requestParentOperation("clear", options).then((result) => {
    if (!result?.cleanup) return null;
    return { cleanup: result.cleanup, dashboard: result.dashboard };
  });
}

export function isParentPwaCacheOperationsRequest(
  value: unknown,
): value is ParentPwaCacheOperationsRequestMessage {
  const payload = messageRecord(value);
  return Boolean(payload)
    && payload?.type === PWA_CACHE_OPERATIONS_REQUEST
    && payload.app_id === "settings"
    && (payload.action === "clear" || payload.action === "diagnostics")
    && validIdentity(payload.request_id);
}

async function requestParentOperation(
  action: PwaCacheOperation,
  options: ParentPwaCacheOperationsOptions,
): Promise<{ cleanup?: CacheCleanupResult; dashboard: PwaCacheDashboard } | null> {
  const parentWindow = options.parentWindow ?? defaultParentWindow();
  if (!parentWindow) return null;
  const parentOrigin = options.parentOrigin === undefined
    ? defaultParentOrigin()
    : exactHttpOrigin(options.parentOrigin);
  if (!parentOrigin) return null;
  const channel = (options.createMessageChannel ?? (() => new MessageChannel()))();
  const requestId = requestIdentity();
  const message: ParentPwaCacheOperationsRequestMessage = {
    action,
    app_id: "settings",
    request_id: requestId,
    type: PWA_CACHE_OPERATIONS_REQUEST,
  };

  return new Promise((resolve, reject) => {
    let accepted = false;
    let settled = false;
    let timer = globalThis.setTimeout(
      () => finish(null),
      positiveTimeout(options.acceptanceTimeoutMs, DEFAULT_ACCEPTANCE_TIMEOUT_MS),
    );

    function cleanup(): void {
      globalThis.clearTimeout(timer);
      channel.port1.close();
    }

    function finish(result: { cleanup?: CacheCleanupResult; dashboard: PwaCacheDashboard } | null): void {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(result);
    }

    function fail(): void {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error("Maverick cache diagnostics are unavailable."));
    }

    channel.port1.addEventListener("message", (event: MessageEvent<unknown>) => {
      const payload = messageRecord(event.data);
      if (!payload || payload.app_id !== "settings" || payload.request_id !== requestId) return;
      if (payload.type === PWA_CACHE_OPERATIONS_ACCEPTED) {
        if (accepted) return;
        accepted = true;
        globalThis.clearTimeout(timer);
        timer = globalThis.setTimeout(
          fail,
          positiveTimeout(options.resultTimeoutMs, DEFAULT_RESULT_TIMEOUT_MS),
        );
        return;
      }
      if (!accepted || payload.type !== PWA_CACHE_OPERATIONS_RESULT) return;
      if (payload.status === "unavailable") {
        finish(null);
        return;
      }
      if (payload.status !== "ok") {
        fail();
        return;
      }
      const dashboard = normalizeDashboard(payload.dashboard);
      const operationCleanup = payload.cleanup === undefined ? undefined : normalizeCleanup(payload.cleanup);
      if (!dashboard || (action === "clear" && !operationCleanup)) {
        fail();
        return;
      }
      finish({ ...(operationCleanup ? { cleanup: operationCleanup } : {}), dashboard });
    });
    channel.port1.start();
    try {
      parentWindow.postMessage(message, parentOrigin, [channel.port2]);
    } catch {
      finish(null);
    }
  });
}

function normalizeDashboard(value: unknown): PwaCacheDashboard | null {
  const payload = messageRecord(value);
  const diagnostics = normalizeDiagnostics(payload?.diagnostics);
  const metrics = normalizeMetrics(payload?.metrics);
  return diagnostics && metrics ? { diagnostics, metrics } : null;
}

function normalizeDiagnostics(value: unknown): CacheDiagnostics | null {
  const payload = messageRecord(value);
  if (!payload || (payload.backend !== "indexeddb" && payload.backend !== "memory")
      || typeof payload.fileCacheAvailable !== "boolean") return null;
  const numbers = [
    "cacheBytes", "entryCount", "fileCacheBytes", "fileCacheEntryCount",
    "pendingCleanupCount", "structuredCacheBytes", "structuredEntryCount",
  ] as const;
  if (numbers.some((field) => !nonNegativeInteger(payload[field]))) return null;
  if (!optionalNonNegativeNumber(payload.originQuotaBytes)
      || !optionalNonNegativeNumber(payload.originUsageBytes)) return null;
  return payload as CacheDiagnostics;
}

function normalizeMetrics(value: unknown): PwaCacheMetricsSnapshot | null {
  const payload = messageRecord(value);
  const counters = messageRecord(payload?.counters);
  const quota = messageRecord(payload?.quota);
  const wait = messageRecord(payload?.requestWait);
  if (!payload || payload.schema !== PWA_CACHE_METRICS_SCHEMA || !counters || !quota || !wait
      || !nonNegativeNumber(payload.updatedAt) || !nonNegativeNumber(payload.windowStartedAt)
      || PWA_CACHE_COUNTER_METRICS.some((name) => !nonNegativeInteger(counters[name]))) return null;
  if (!optionalNonNegativeNumber(quota.lastEstimatedAt)
      || !optionalNonNegativeNumber(quota.quotaBytes)
      || !optionalNonNegativeNumber(quota.usageBytes)
      || (quota.supported !== null && typeof quota.supported !== "boolean")) return null;
  for (const field of [
    "averageDurationMs", "durationObservations", "maxDurationMs", "pendingCount", "totalDurationMs",
  ]) {
    if (!nonNegativeInteger(wait[field])) return null;
  }
  if (!optionalNonNegativeNumber(wait.oldestPendingMs)) return null;
  return payload as PwaCacheMetricsSnapshot;
}

function normalizeCleanup(value: unknown): CacheCleanupResult | null {
  const payload = messageRecord(value);
  if (!payload || (payload.status !== "complete" && payload.status !== "pending")
      || !nonNegativeInteger(payload.pendingCleanupCount) || !nonNegativeInteger(payload.removed)) return null;
  return payload as CacheCleanupResult;
}

function defaultParentWindow(): ParentMessageWindow | null {
  return typeof window !== "undefined" && window.parent !== window ? window.parent : null;
}

function defaultParentOrigin(): string | null {
  if (typeof window === "undefined") return null;
  const platformOrigin = exactHttpOrigin(
    (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown }).__MAVERICK_PLATFORM_ORIGIN__,
  );
  const frameOrigin = exactHttpOrigin(window.location.origin);
  return platformOrigin && frameOrigin && platformOrigin !== frameOrigin ? platformOrigin : null;
}

function exactHttpOrigin(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const parsed = new URL(value);
    return parsed.origin === value && (parsed.protocol === "http:" || parsed.protocol === "https:")
      ? parsed.origin
      : null;
  } catch {
    return null;
  }
}

function requestIdentity(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function positiveTimeout(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.min(Math.floor(value), 30_000)
    : fallback;
}

function validIdentity(value: unknown): value is string {
  return typeof value === "string" && value.trim() === value
    && value.length > 0 && value.length <= MAX_IDENTITY_LENGTH
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

function nonNegativeInteger(value: unknown): boolean {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nonNegativeNumber(value: unknown): boolean {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function optionalNonNegativeNumber(value: unknown): boolean {
  return value === null || nonNegativeNumber(value);
}

function messageRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}
