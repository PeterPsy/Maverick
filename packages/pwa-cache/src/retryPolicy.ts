import mutationRetryRegistry from "./mutationRetryRegistry.v1.json";

export type RetryDisposition = "retryable" | "terminal" | "cancelled";

export type RetryClassification = {
  disposition: RetryDisposition;
  retryAfterMs?: number;
};

export type MutationRetryContract = {
  auditId: string;
  idempotencyKey: string;
  requestFingerprint: string;
  serverDeduplicates: true;
};

export type RetryTelemetryEvent = {
  attempt: number;
  durationMs?: number;
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
const SHA256_FINGERPRINT_PATTERN = /^sha256:[0-9a-f]{64}$/u;
const RETRY_AUDIT_ID_PATTERN = /^[a-z0-9][a-z0-9.-]{4,126}\.v[1-9][0-9]*$/u;
const MUTATION_RETRY_REGISTRY_SCHEMA = "maverick.pwa-mutation-retry-registry.v1";
export const APPROVED_MUTATION_RETRY_AUDIT_IDS = approvedMutationRetryAuditIds();
const APPROVED_MUTATION_RETRY_AUDIT_ID_SET = new Set(APPROVED_MUTATION_RETRY_AUDIT_IDS);

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

export async function createRequestFingerprint(serializedRequest: string): Promise<string> {
  if (typeof serializedRequest !== "string" || !serializedRequest.length) {
    throw new TypeError("Mutation retry request fingerprint input is required.");
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error("SHA-256 is unavailable; this mutation cannot be retried safely.");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(serializedRequest));
  return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function idempotencyHeaders(contract: MutationRetryContract): Record<string, string> {
  validateMutationContract("POST", contract);
  return { "Idempotency-Key": contract.idempotencyKey };
}

export function validateMutationContract(
  method: string,
  contract: MutationRetryContract | undefined,
): void {
  if (SAFE_METHODS.has(method) || !contract) {
    return;
  }
  if (contract.serverDeduplicates !== true
      || !RETRY_AUDIT_ID_PATTERN.test(contract.auditId)
      || !IDEMPOTENCY_KEY_PATTERN.test(contract.idempotencyKey)
      || !SHA256_FINGERPRINT_PATTERN.test(contract.requestFingerprint)) {
    throw new TypeError("Mutation retry requires a registered audit id, stable Idempotency-Key, canonical SHA-256 request fingerprint, and server deduplication.");
  }
  if (!APPROVED_MUTATION_RETRY_AUDIT_ID_SET.has(contract.auditId)) {
    throw new TypeError("Mutation retry audit id is absent from the approved audit registry.");
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

function approvedMutationRetryAuditIds(): readonly string[] {
  const values: unknown = mutationRetryRegistry.audit_ids;
  if (mutationRetryRegistry.schema !== MUTATION_RETRY_REGISTRY_SCHEMA || !Array.isArray(values)) {
    return Object.freeze([]);
  }
  const ids = values.filter((value): value is string => typeof value === "string");
  if (ids.length !== values.length
      || new Set(ids).size !== ids.length
      || ids.some((auditId) => !RETRY_AUDIT_ID_PATTERN.test(auditId))) {
    return Object.freeze([]);
  }
  return Object.freeze([...ids]);
}

function isAbortError(error: unknown): boolean {
  return error instanceof RetryCancelledError
    || (Boolean(error) && typeof error === "object" && (error as { name?: unknown }).name === "AbortError");
}

function finiteDelay(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}
