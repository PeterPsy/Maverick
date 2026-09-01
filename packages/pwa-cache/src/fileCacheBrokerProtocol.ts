export const PWA_FILE_CACHE_BROKER_OPEN = "maverick.storage.file-cache.open.v1";
export const PWA_FILE_CACHE_BROKER_ACCEPTED = "maverick.storage.file-cache.accepted.v1";
export const PWA_FILE_CACHE_BROKER_RESULT = "maverick.storage.file-cache.result.v1";
export const PWA_FILE_CACHE_BROKER_CANCEL = "maverick.storage.file-cache.cancel.v1";

const DEFAULT_ACCEPTANCE_TIMEOUT_MS = 750;
const MAX_IDENTITY_LENGTH = 256;

export type ParentFileCacheOpenRequest = {
  fileId: string;
  sourceVersion: string;
};

export type ParentFileCacheOpenResult = {
  blob: Blob;
  source: "cache" | "network";
};

export type ParentFileCacheOpenMessage = {
  app_id: "storage";
  file_id: string;
  request_id: string;
  source_version: string;
  type: typeof PWA_FILE_CACHE_BROKER_OPEN;
};

export type ParentFileCacheCancelMessage = {
  request_id: string;
  type: typeof PWA_FILE_CACHE_BROKER_CANCEL;
};

export type ParentFileCacheAcceptedMessage = {
  app_id: "storage";
  request_id: string;
  type: typeof PWA_FILE_CACHE_BROKER_ACCEPTED;
};

export type ParentFileCacheResultMessage = {
  app_id: "storage";
  blob?: Blob;
  request_id: string;
  source?: "cache" | "network";
  status: "error" | "ok" | "unavailable";
  type: typeof PWA_FILE_CACHE_BROKER_RESULT;
};

export type ParentFileCacheClientOptions = {
  acceptanceTimeoutMs?: number;
  createMessageChannel?: () => MessageChannel;
  parentOrigin?: string;
  parentWindow?: Pick<Window, "postMessage">;
  signal?: AbortSignal;
};

export function requestParentFileCacheOpen(
  request: ParentFileCacheOpenRequest,
  options: ParentFileCacheClientOptions = {},
): Promise<ParentFileCacheOpenResult | null> {
  const fileId = boundedIdentity(request.fileId);
  const sourceVersion = boundedIdentity(request.sourceVersion);
  const parentWindow = options.parentWindow ?? defaultParentWindow();
  if (!parentWindow) return Promise.resolve(null);
  if (options.signal?.aborted) return Promise.reject(abortError(options.signal));

  const parentOrigin = options.parentOrigin === undefined
    ? defaultParentOrigin()
    : exactHttpOrigin(options.parentOrigin);
  if (!parentOrigin) return Promise.resolve(null);

  const channel = (options.createMessageChannel ?? (() => new MessageChannel()))();
  const requestId = requestIdentity();
  const acceptanceTimeoutMs = positiveTimeout(options.acceptanceTimeoutMs);
  const message: ParentFileCacheOpenMessage = {
    app_id: "storage",
    file_id: fileId,
    request_id: requestId,
    source_version: sourceVersion,
    type: PWA_FILE_CACHE_BROKER_OPEN,
  };

  return new Promise((resolve, reject) => {
    let accepted = false;
    let settled = false;
    const timeout = globalThis.setTimeout(() => finish(null), acceptanceTimeoutMs);

    function cleanup(): void {
      globalThis.clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abort);
      channel.port1.close();
    }

    function finish(result: ParentFileCacheOpenResult | null): void {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(result);
    }

    function fail(error: unknown): void {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    }

    function abort(): void {
      try {
        channel.port1.postMessage({ request_id: requestId, type: PWA_FILE_CACHE_BROKER_CANCEL } satisfies ParentFileCacheCancelMessage);
      } finally {
        fail(abortError(options.signal));
      }
    }

    channel.port1.addEventListener("message", (event: MessageEvent<unknown>) => {
      const payload = messageRecord(event.data);
      if (!payload || payload.request_id !== requestId || payload.app_id !== "storage") return;
      if (payload.type === PWA_FILE_CACHE_BROKER_ACCEPTED) {
        accepted = true;
        globalThis.clearTimeout(timeout);
        return;
      }
      if (!accepted || payload.type !== PWA_FILE_CACHE_BROKER_RESULT) return;
      if (payload.status === "unavailable") {
        finish(null);
        return;
      }
      if (payload.status === "ok" && payload.blob instanceof Blob
          && (payload.source === "cache" || payload.source === "network")) {
        finish({ blob: payload.blob, source: payload.source });
        return;
      }
      fail(new Error("Storage file could not be opened."));
    });
    channel.port1.start();
    options.signal?.addEventListener("abort", abort, { once: true });

    try {
      parentWindow.postMessage(message, parentOrigin, [channel.port2]);
    } catch {
      finish(null);
    }
  });
}

export function isParentFileCacheOpenMessage(value: unknown): value is ParentFileCacheOpenMessage {
  const payload = messageRecord(value);
  return Boolean(payload)
    && payload?.type === PWA_FILE_CACHE_BROKER_OPEN
    && payload.app_id === "storage"
    && validIdentity(payload.request_id)
    && validIdentity(payload.file_id)
    && validIdentity(payload.source_version);
}

export function isParentFileCacheCancelMessage(value: unknown, requestId: string): value is ParentFileCacheCancelMessage {
  const payload = messageRecord(value);
  return Boolean(payload)
    && payload?.type === PWA_FILE_CACHE_BROKER_CANCEL
    && payload.request_id === requestId;
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

function boundedIdentity(value: string): string {
  const normalized = String(value || "").trim();
  if (!validIdentity(normalized)) throw new TypeError("Storage file cache identity is invalid.");
  return normalized;
}

function messageRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function abortError(signal: AbortSignal | undefined): unknown {
  return signal?.reason instanceof Error
    ? signal.reason
    : new DOMException("Storage file open was cancelled.", "AbortError");
}
