import type {
  CacheLoader,
  CacheNetworkResult,
  CacheReadResult,
  CacheRevalidationResult,
} from "./types";

export const PWA_DATA_CACHE_BROKER_OPEN = "maverick.pwa.data-cache.open.v1";
export const PWA_DATA_CACHE_BROKER_ACCEPTED = "maverick.pwa.data-cache.accepted.v1";
export const PWA_DATA_CACHE_BROKER_NETWORK_REQUEST = "maverick.pwa.data-cache.network-request.v1";
export const PWA_DATA_CACHE_BROKER_NETWORK_RESULT = "maverick.pwa.data-cache.network-result.v1";
export const PWA_DATA_CACHE_BROKER_RESULT = "maverick.pwa.data-cache.result.v1";
export const PWA_DATA_CACHE_BROKER_INVALIDATE = "maverick.pwa.data-cache.invalidate.v1";
export const PWA_DATA_CACHE_BROKER_CANCEL = "maverick.pwa.data-cache.cancel.v1";

const DEFAULT_ACCEPTANCE_TIMEOUT_MS = 750;
const MAX_IDENTITY_LENGTH = 256;

export type ParentDataCacheMigrationSeed<T = unknown> = {
  etag?: string;
  payload: T;
  revision: string;
};

export type ParentDataCacheReadRequest<T = unknown> = {
  appId: string;
  entityId: string;
  migrationSeed?: ParentDataCacheMigrationSeed<T>;
  resource: string;
  schemaRevision: string;
};

export type ParentDataCacheReadResult<T> = CacheReadResult<T> & {
  brokered: boolean;
  migrationCommitted: boolean;
};

export type ParentDataCacheClientOptions<T> = {
  acceptanceTimeoutMs?: number;
  createMessageChannel?: () => MessageChannel;
  parentOrigin?: string;
  parentWindow?: Pick<Window, "postMessage">;
  sanitize: (payload: unknown) => T | null;
  signal?: AbortSignal;
};

export type ParentDataCacheOpenMessage = {
  app_id: string;
  entity_id: string;
  migration_seed?: ParentDataCacheMigrationSeed;
  request_id: string;
  resource: string;
  schema_revision: string;
  type: typeof PWA_DATA_CACHE_BROKER_OPEN;
};

export type ParentDataCacheAcceptedMessage = {
  app_id: string;
  request_id: string;
  type: typeof PWA_DATA_CACHE_BROKER_ACCEPTED;
};

export type ParentDataCacheNetworkRequestMessage = {
  app_id: string;
  etag?: string;
  known_revision?: string;
  network_request_id: string;
  request_id: string;
  type: typeof PWA_DATA_CACHE_BROKER_NETWORK_REQUEST;
};

export type ParentDataCacheSerializedError = {
  name: "AbortError" | "MaverickHttpError" | "MaverickTransportError" | "TerminalError" | "TimeoutError";
  retry_after_ms?: number;
  status?: number;
};

export type ParentDataCacheNetworkResultMessage = {
  app_id: string;
  error?: ParentDataCacheSerializedError;
  etag?: string;
  kind?: "not_modified" | "value";
  network_request_id: string;
  payload?: unknown;
  request_id: string;
  revision?: string;
  status: "error" | "ok";
  type: typeof PWA_DATA_CACHE_BROKER_NETWORK_RESULT;
};

export type ParentDataCacheResultMessage = {
  app_id: string;
  changed?: boolean;
  freshness?: "fresh" | "stale";
  has_revalidation?: boolean;
  migration_committed?: boolean;
  payload?: unknown;
  phase: "initial" | "revalidation";
  request_id: string;
  revision?: string;
  source?: "cache" | "network";
  status: "error" | "ok" | "unavailable";
  type: typeof PWA_DATA_CACHE_BROKER_RESULT;
};

export type ParentDataCacheCancelMessage = {
  request_id: string;
  type: typeof PWA_DATA_CACHE_BROKER_CANCEL;
};

export type ParentDataCacheInvalidateMessage = {
  request_id: string;
  type: typeof PWA_DATA_CACHE_BROKER_INVALIDATE;
};

/**
 * Read one app-owned model through the top-level cache broker. Embedded apps
 * never receive a storage handle or a host-attested principal. When the broker
 * is absent or disabled this deliberately falls back to one normal server read.
 */
export async function readThroughParentDataCache<T>(
  request: ParentDataCacheReadRequest<T>,
  loader: CacheLoader<T>,
  options: ParentDataCacheClientOptions<T>,
): Promise<ParentDataCacheReadResult<T>> {
  const normalized = normalizeReadRequest(request, options.sanitize);
  const brokered = await requestBrokeredRead(normalized, loader, options);
  if (brokered) return brokered;
  return directRead(loader, options.sanitize, options.signal);
}

export function isParentDataCacheOpenMessage(value: unknown): value is ParentDataCacheOpenMessage {
  const payload = messageRecord(value);
  if (!payload
      || payload.type !== PWA_DATA_CACHE_BROKER_OPEN
      || !validIdentity(payload.app_id)
      || !validIdentity(payload.entity_id)
      || !validIdentity(payload.request_id)
      || !validIdentity(payload.resource)
      || !validIdentity(payload.schema_revision)) {
    return false;
  }
  if (payload.migration_seed === undefined) return true;
  const seed = messageRecord(payload.migration_seed);
  return Boolean(seed)
    && validRevision(seed?.revision)
    && validOptionalRevision(seed?.etag)
    && Object.prototype.hasOwnProperty.call(seed, "payload");
}

export function isParentDataCacheCancelMessage(
  value: unknown,
  requestId: string,
): value is ParentDataCacheCancelMessage {
  const payload = messageRecord(value);
  return Boolean(payload)
    && payload?.type === PWA_DATA_CACHE_BROKER_CANCEL
    && payload.request_id === requestId;
}

export function isParentDataCacheInvalidateMessage(
  value: unknown,
  requestId: string,
): value is ParentDataCacheInvalidateMessage {
  const payload = messageRecord(value);
  return Boolean(payload)
    && payload?.type === PWA_DATA_CACHE_BROKER_INVALIDATE
    && payload.request_id === requestId;
}

export function isParentDataCacheNetworkResultMessage(
  value: unknown,
  requestId: string,
  networkRequestId: string,
): value is ParentDataCacheNetworkResultMessage {
  const payload = messageRecord(value);
  if (!payload
      || payload.type !== PWA_DATA_CACHE_BROKER_NETWORK_RESULT
      || payload.request_id !== requestId
      || payload.network_request_id !== networkRequestId
      || !validIdentity(payload.app_id)
      || (payload.status !== "ok" && payload.status !== "error")) {
    return false;
  }
  if (payload.status === "error") return validSerializedError(payload.error);
  if (payload.kind === "not_modified") {
    return validOptionalRevision(payload.revision) && validOptionalRevision(payload.etag);
  }
  return payload.kind === "value"
    && validRevision(payload.revision)
    && validOptionalRevision(payload.etag)
    && Object.prototype.hasOwnProperty.call(payload, "payload");
}

/** Accept app lifecycle/navigation messages only from the exact shell parent. */
export function isExactMaverickParentMessage(
  event: Pick<MessageEvent, "origin" | "source">,
): boolean {
  if (typeof window === "undefined") return false;
  const parentOrigin = defaultParentOrigin();
  if (parentOrigin) {
    return event.source === window.parent && event.origin === parentOrigin;
  }
  const localOrigin = exactHttpOrigin(window.location.origin);
  return window.parent === window
    && event.source === window
    && Boolean(localOrigin && event.origin === localOrigin);
}

export function serializeParentDataCacheError(error: unknown): ParentDataCacheSerializedError {
  const record = error && typeof error === "object" ? error as Record<string, unknown> : {};
  const rawName = typeof record.name === "string" ? record.name : "";
  const status = typeof record.status === "number"
      && Number.isInteger(record.status)
      && record.status >= 100
      && record.status <= 599
    ? record.status
    : undefined;
  const retryAfterMs = finiteDelay(record.retryAfterMs);
  const name: ParentDataCacheSerializedError["name"] = status !== undefined
    ? "MaverickHttpError"
    : rawName === "AbortError"
      ? "AbortError"
      : rawName === "MaverickTransportError"
        ? "MaverickTransportError"
        : rawName === "TimeoutError"
          ? "TimeoutError"
          : "TerminalError";
  return {
    name,
    ...(status === undefined ? {} : { status }),
    ...(retryAfterMs === undefined ? {} : { retry_after_ms: retryAfterMs }),
  };
}

async function requestBrokeredRead<T>(
  request: ParentDataCacheOpenMessage,
  loader: CacheLoader<T>,
  options: ParentDataCacheClientOptions<T>,
): Promise<ParentDataCacheReadResult<T> | null> {
  const parentWindow = options.parentWindow ?? defaultParentWindow();
  if (!parentWindow) return null;
  if (options.signal?.aborted) throw abortError(options.signal);
  const parentOrigin = options.parentOrigin === undefined
    ? defaultParentOrigin()
    : exactHttpOrigin(options.parentOrigin);
  if (!parentOrigin) return null;

  const channel = (options.createMessageChannel ?? (() => new MessageChannel()))();
  const localController = new AbortController();
  const relayAbort = () => localController.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", relayAbort, { once: true });

  return new Promise((resolve, reject) => {
    let accepted = false;
    let initialSettled = false;
    let finished = false;
    let lastLoaderError: unknown;
    let resolveRevalidation: ((value: CacheRevalidationResult<T>) => void) | null = null;
    let rejectRevalidation: ((reason: unknown) => void) | null = null;
    const timeout = globalThis.setTimeout(() => finish(null), positiveTimeout(options.acceptanceTimeoutMs));

    function cleanup(): void {
      globalThis.clearTimeout(timeout);
      options.signal?.removeEventListener("abort", relayAbort);
      localController.signal.removeEventListener("abort", cancelBroker);
      localController.abort(new DOMException("Broker read closed.", "AbortError"));
      channel.port1.close();
    }

    function finish(value: ParentDataCacheReadResult<T> | null): void {
      if (finished) return;
      finished = true;
      cleanup();
      if (!initialSettled) {
        initialSettled = true;
        resolve(value);
      }
    }

    function fail(error: unknown): void {
      if (finished) return;
      finished = true;
      cleanup();
      if (!initialSettled) {
        initialSettled = true;
        reject(error);
      } else {
        rejectRevalidation?.(error);
      }
    }

    function cancelBroker(): void {
      try {
        channel.port1.postMessage({
          request_id: request.request_id,
          type: PWA_DATA_CACHE_BROKER_CANCEL,
        } satisfies ParentDataCacheCancelMessage);
      } finally {
        fail(abortError(options.signal));
      }
    }

    async function serveNetwork(payload: ParentDataCacheNetworkRequestMessage): Promise<void> {
      try {
        const response = await loader({
          ...(payload.etag ? { etag: payload.etag } : {}),
          ...(payload.known_revision ? { knownRevision: payload.known_revision } : {}),
          signal: localController.signal,
        });
        const normalizedResponse = normalizeNetworkResult(response, options.sanitize);
        channel.port1.postMessage({
          app_id: request.app_id,
          network_request_id: payload.network_request_id,
          request_id: request.request_id,
          status: "ok",
          type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
          ...networkResultMessage(normalizedResponse),
        } satisfies ParentDataCacheNetworkResultMessage);
      } catch (error) {
        lastLoaderError = error;
        try {
          channel.port1.postMessage({
            app_id: request.app_id,
            error: serializeParentDataCacheError(error),
            network_request_id: payload.network_request_id,
            request_id: request.request_id,
            status: "error",
            type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
          } satisfies ParentDataCacheNetworkResultMessage);
        } catch {
          fail(error);
        }
      }
    }

    function receiveResult(payload: Record<string, unknown>): void {
      if (payload.status === "unavailable" && payload.phase === "initial") {
        finish(null);
        return;
      }
      if (payload.status !== "ok") {
        fail(lastLoaderError ?? new Error("The parent data-cache read failed."));
        return;
      }
      const revision = validRevision(payload.revision) ? payload.revision : null;
      const sanitized = options.sanitize(payload.payload);
      if (!revision || sanitized === null) {
        try {
          channel.port1.postMessage({
            request_id: request.request_id,
            type: PWA_DATA_CACHE_BROKER_INVALIDATE,
          } satisfies ParentDataCacheInvalidateMessage);
        } catch {
          // The local sanitizer still fails closed if the port is already gone.
        }
        if (payload.phase === "initial") finish(null);
        else fail(new TypeError("The parent data-cache payload did not match the app schema."));
        return;
      }
      if (payload.phase === "revalidation") {
        if (!initialSettled || typeof payload.changed !== "boolean") return;
        resolveRevalidation?.({ changed: payload.changed, payload: sanitized, revision });
        finished = true;
        cleanup();
        return;
      }
      if (initialSettled
          || (payload.freshness !== "fresh" && payload.freshness !== "stale")
          || (payload.source !== "cache" && payload.source !== "network")) {
        return;
      }
      const hasRevalidation = payload.has_revalidation === true;
      let revalidation: Promise<CacheRevalidationResult<T>> | undefined;
      if (hasRevalidation) {
        revalidation = new Promise((resolveDeferred, rejectDeferred) => {
          resolveRevalidation = resolveDeferred;
          rejectRevalidation = rejectDeferred;
        });
        void revalidation.catch(() => undefined);
      }
      initialSettled = true;
      resolve({
        brokered: true,
        freshness: payload.freshness,
        migrationCommitted: payload.migration_committed === true,
        payload: sanitized,
        ...(revalidation ? { revalidation } : {}),
        revision,
        source: payload.source,
      });
      if (!hasRevalidation) {
        finished = true;
        cleanup();
      }
    }

    channel.port1.addEventListener("message", (event: MessageEvent<unknown>) => {
      const payload = messageRecord(event.data);
      if (!payload || payload.request_id !== request.request_id || payload.app_id !== request.app_id) return;
      if (payload.type === PWA_DATA_CACHE_BROKER_ACCEPTED) {
        accepted = true;
        globalThis.clearTimeout(timeout);
        return;
      }
      if (!accepted) return;
      if (payload.type === PWA_DATA_CACHE_BROKER_NETWORK_REQUEST
          && validIdentity(payload.network_request_id)
          && validOptionalRevision(payload.etag)
          && validOptionalRevision(payload.known_revision)) {
        void serveNetwork(payload as ParentDataCacheNetworkRequestMessage);
        return;
      }
      if (payload.type === PWA_DATA_CACHE_BROKER_RESULT
          && (payload.phase === "initial" || payload.phase === "revalidation")) {
        receiveResult(payload);
      }
    });
    channel.port1.start();
    localController.signal.addEventListener("abort", cancelBroker, { once: true });

    try {
      parentWindow.postMessage(request, parentOrigin, [channel.port2]);
    } catch {
      finish(null);
    }
  });
}

async function directRead<T>(
  loader: CacheLoader<T>,
  sanitize: (payload: unknown) => T | null,
  signal?: AbortSignal,
): Promise<ParentDataCacheReadResult<T>> {
  if (signal?.aborted) throw abortError(signal);
  const response = normalizeNetworkResult(await loader({ signal }), sanitize);
  if (response.kind === "not_modified") {
    throw new Error("A not_modified response requires a cached value.");
  }
  return {
    brokered: false,
    freshness: "fresh",
    migrationCommitted: false,
    payload: response.payload,
    revision: response.revision,
    source: "network",
  };
}

function normalizeReadRequest<T>(
  request: ParentDataCacheReadRequest<T>,
  sanitize: (payload: unknown) => T | null,
): ParentDataCacheOpenMessage {
  const migrationSeed = request.migrationSeed
    ? normalizeMigrationSeed(request.migrationSeed, sanitize)
    : undefined;
  return {
    app_id: boundedIdentity(request.appId, "app"),
    entity_id: boundedIdentity(request.entityId, "entity"),
    ...(migrationSeed ? { migration_seed: migrationSeed } : {}),
    request_id: requestIdentity(),
    resource: boundedIdentity(request.resource, "resource"),
    schema_revision: boundedIdentity(request.schemaRevision, "schema revision"),
    type: PWA_DATA_CACHE_BROKER_OPEN,
  };
}

function normalizeMigrationSeed<T>(
  seed: ParentDataCacheMigrationSeed<T>,
  sanitize: (payload: unknown) => T | null,
): ParentDataCacheMigrationSeed<T> {
  const payload = sanitize(seed.payload);
  if (payload === null) throw new TypeError("The data-cache migration payload is invalid.");
  return {
    ...(seed.etag ? { etag: boundedRevision(seed.etag) } : {}),
    payload,
    revision: boundedRevision(seed.revision),
  };
}

function normalizeNetworkResult<T>(
  result: CacheNetworkResult<T>,
  sanitize: (payload: unknown) => T | null,
): CacheNetworkResult<T> {
  if (result.kind === "not_modified") {
    return {
      kind: "not_modified",
      ...(result.etag ? { etag: boundedRevision(result.etag) } : {}),
      ...(result.revision ? { revision: boundedRevision(result.revision) } : {}),
    };
  }
  const payload = sanitize(result.payload);
  if (payload === null) throw new TypeError("The data-cache network payload is invalid.");
  return {
    ...(result.etag ? { etag: boundedRevision(result.etag) } : {}),
    kind: "value",
    payload,
    revision: boundedRevision(result.revision),
  };
}

function networkResultMessage<T>(result: CacheNetworkResult<T>): Pick<
  ParentDataCacheNetworkResultMessage,
  "etag" | "kind" | "payload" | "revision"
> {
  return result.kind === "not_modified"
    ? {
        kind: "not_modified",
        ...(result.etag ? { etag: result.etag } : {}),
        ...(result.revision ? { revision: result.revision } : {}),
      }
    : {
        kind: "value",
        payload: result.payload,
        revision: result.revision,
        ...(result.etag ? { etag: result.etag } : {}),
      };
}

function validSerializedError(value: unknown): value is ParentDataCacheSerializedError {
  const payload = messageRecord(value);
  if (!payload || ![
    "AbortError",
    "MaverickHttpError",
    "MaverickTransportError",
    "TerminalError",
    "TimeoutError",
  ].includes(String(payload.name || ""))) return false;
  if (payload.status !== undefined
      && (typeof payload.status !== "number"
        || !Number.isInteger(payload.status)
        || payload.status < 100
        || payload.status > 599)) return false;
  return payload.retry_after_ms === undefined || finiteDelay(payload.retry_after_ms) !== undefined;
}

function defaultParentWindow(): Pick<Window, "postMessage"> | null {
  if (typeof window === "undefined" || window.parent === window) return null;
  return window.parent;
}

function defaultParentOrigin(): string | null {
  if (typeof window === "undefined") return null;
  const platformOrigin = exactHttpOrigin(
    (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown }).__MAVERICK_PLATFORM_ORIGIN__,
  );
  const frameOrigin = exactHttpOrigin(window.location.origin);
  return platformOrigin && frameOrigin && platformOrigin !== frameOrigin
    ? platformOrigin
    : null;
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

function positiveTimeout(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.min(Math.floor(value), 10_000)
    : DEFAULT_ACCEPTANCE_TIMEOUT_MS;
}

function validIdentity(value: unknown): value is string {
  return typeof value === "string"
    && value.trim() === value
    && value.length > 0
    && value.length <= MAX_IDENTITY_LENGTH
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

function validRevision(value: unknown): value is string {
  return validIdentity(value);
}

function validOptionalRevision(value: unknown): value is string | undefined {
  return value === undefined || validRevision(value);
}

function boundedIdentity(value: string, label: string): string {
  const normalized = String(value || "").trim();
  if (!validIdentity(normalized)) throw new TypeError(`PWA data-cache ${label} is invalid.`);
  return normalized;
}

function boundedRevision(value: string): string {
  return boundedIdentity(value, "revision");
}

function finiteDelay(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.min(value, 60_000)
    : undefined;
}

function messageRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function abortError(signal: AbortSignal | undefined): unknown {
  return signal?.reason instanceof Error
    ? signal.reason
    : new DOMException("The PWA data-cache read was cancelled.", "AbortError");
}
