import type { MutationRetryExecutor } from "./mutationRetry";
import type { SafeRequestRetryExecutor } from "./safeRequestRetry";

export type RetryDisposition = "retryable" | "terminal" | "cancelled";

export type RetryClassification = {
  disposition: RetryDisposition;
  retryAfterMs?: number;
};

export type RetryTelemetryEvent = {
  attempt: number;
  durationMs?: number;
  keyHash: string;
  kind: "wait_started" | "retry_attempt" | "resolved" | "cancelled";
  waitMs?: number;
};

export type OpaqueRetryOperationOptions<T> = {
  key: string;
  operation: (context: { attempt: number; signal: AbortSignal }) => Promise<T>;
  signal?: AbortSignal;
  action?: never;
  classify?: never;
  endpoint?: never;
  executor?: never;
  method?: never;
  mutation?: never;
};

export type SafeRequestRetryOperationOptions = {
  executor: SafeRequestRetryExecutor;
  key: string;
  signal?: AbortSignal;
};

export type MutationRetryOperationOptions = {
  executor: MutationRetryExecutor;
  key: string;
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
