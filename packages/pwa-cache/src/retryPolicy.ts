export type RetryDisposition = "retryable" | "terminal" | "cancelled";

export type RetryClassification = {
  disposition: RetryDisposition;
  retryAfterMs?: number;
};

export type MutationRetryContract = {
  idempotencyKey: string;
  requestFingerprint: string;
  serverDeduplicates: true;
};

export type RetryTelemetryEvent = {
  attempt: number;
  keyHash: string;
  kind: "wait_started" | "retry_attempt" | "resolved" | "cancelled";
  waitMs?: number;
};

export type RetryOperationOptions<T> = {
  classify?: (error: unknown) => RetryClassification;
  key: string;
  method?: string;
  mutation?: MutationRetryContract;
  operation: (context: { attempt: number; signal: AbortSignal }) => Promise<T>;
  signal?: AbortSignal;
};

export type RetryCoordinatorOptions = {
  baseDelayMs?: number;
  capDelayMs?: number;
  isVisible?: () => boolean;
  maxMutationAttempts?: number;
  minRetryIntervalMs?: number;
  now?: () => number;
  random?: () => number;
  setTimer?: (callback: () => void, delayMs: number) => unknown;
  clearTimer?: (timer: unknown) => void;
  telemetry?: (event: RetryTelemetryEvent) => void;
};

export const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const RETRYABLE_HTTP_STATUSES = new Set([429, 502, 503, 504]);
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{15,199}$/u;

export class RetryCancelledError extends Error {
  constructor(message = "Retry operation was cancelled.") {
    super(message);
    this.name = "RetryCancelledError";
  }
}

export function classifyRetryError(error: unknown): RetryClassification {
  if (isAbortError(error)) {
    return { disposition: "cancelled" };
  }
  const record = error && typeof error === "object" ? error as Record<string, unknown> : {};
  const status = typeof record.status === "number" ? record.status : null;
  if (status !== null) {
    return RETRYABLE_HTTP_STATUSES.has(status)
      ? { disposition: "retryable", retryAfterMs: finiteDelay(record.retryAfterMs) }
      : { disposition: "terminal" };
  }
  const name = typeof record.name === "string" ? record.name : "";
  return name === "MaverickTransportError" || name === "TimeoutError"
    ? { disposition: "retryable" }
    : { disposition: "terminal" };
}

export function createIdempotencyKey(prefix = "mvr"): string {
  const normalizedPrefix = prefix.replace(/[^A-Za-z0-9]/g, "").slice(0, 16) || "mvr";
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${normalizedPrefix}:${random}`;
}

export function idempotencyHeaders(contract: MutationRetryContract): Record<string, string> {
  validateMutationContract("POST", contract);
  return { "Idempotency-Key": contract.idempotencyKey };
}

export function validateMutationContract(method: string, contract: MutationRetryContract | undefined): void {
  if (SAFE_METHODS.has(method) || !contract) {
    return;
  }
  if (contract.serverDeduplicates !== true
      || !IDEMPOTENCY_KEY_PATTERN.test(contract.idempotencyKey)
      || !contract.requestFingerprint.trim()) {
    throw new TypeError("Mutation retry requires a stable Idempotency-Key, request fingerprint, and server deduplication.");
  }
}

export function validateOperationKey(key: string): string {
  const normalized = String(key || "").trim();
  if (!normalized || normalized.length > 512) {
    throw new TypeError("Retry operation key is required and must be bounded.");
  }
  return normalized;
}

export function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw cancellationFromSignal(signal);
  }
}

export function cancellationFromSignal(signal: AbortSignal): RetryCancelledError {
  return signal.reason instanceof RetryCancelledError ? signal.reason : new RetryCancelledError();
}

export function positive(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

export function clamp(value: number, lower: number, upper: number): number {
  return Math.min(upper, Math.max(lower, value));
}

export function stableHash(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function createTelemetrySalt(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}:${Math.random().toString(36).slice(2)}`;
}

export function trimOldestStringMap(map: Map<string, string>, limit: number): void {
  while (map.size > limit) {
    const oldest = map.keys().next().value;
    if (typeof oldest !== "string") return;
    map.delete(oldest);
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof RetryCancelledError
    || (Boolean(error) && typeof error === "object" && (error as { name?: unknown }).name === "AbortError");
}

function finiteDelay(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}
