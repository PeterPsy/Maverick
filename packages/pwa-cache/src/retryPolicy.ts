import mutationRetryRegistry from "./mutationRetryRegistry.v2.json";

export type RetryDisposition = "retryable" | "terminal" | "cancelled";

export type RetryClassification = {
  disposition: RetryDisposition;
  retryAfterMs?: number;
};

const MUTATION_RETRY_CONTRACT_BRAND: unique symbol = Symbol("maverick.mutation-retry-contract");

export type MutationRetryTarget = Readonly<{
  action: string;
  endpoint: string;
  method: string;
}>;

export type MutationRetryContractInput = MutationRetryTarget & Readonly<{
  auditId: string;
  idempotencyKey: string;
  requestFingerprint: string;
}>;

export type MutationRetryContract = MutationRetryContractInput & Readonly<{
  [MUTATION_RETRY_CONTRACT_BRAND]: true;
  serverDeduplicates: true;
}>;

export type RetryTelemetryEvent = {
  attempt: number;
  durationMs?: number;
  keyHash: string;
  kind: "wait_started" | "retry_attempt" | "resolved" | "cancelled";
  waitMs?: number;
};

type RetryOperationBase<T> = {
  classify?: (error: unknown) => RetryClassification;
  key: string;
  operation: (context: { attempt: number; signal: AbortSignal }) => Promise<T>;
  signal?: AbortSignal;
};

export type RetryOperationOptions<T> = RetryOperationBase<T> & ({
  action: string;
  endpoint: string;
  method: string;
  mutation: MutationRetryContract;
} | {
  action?: string;
  endpoint?: string;
  method?: string;
  mutation?: undefined;
});

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
const MUTATION_ACTION_PATTERN = /^[a-z0-9][a-z0-9._:-]{1,127}$/u;
const MUTATION_ENDPOINT_PATTERN = /^\/api\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,506}$/u;
const MUTATION_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const MUTATION_RETRY_REGISTRY_SCHEMA = "maverick.pwa-mutation-retry-registry.v2";
const APPROVED_MUTATION_RETRY_CONTRACTS = approvedMutationRetryContracts();
export const APPROVED_MUTATION_RETRY_AUDIT_IDS = Object.freeze([
  ...APPROVED_MUTATION_RETRY_CONTRACTS.keys(),
]);
const ISSUED_MUTATION_RETRY_CONTRACTS = new WeakSet<object>();

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

export function createMutationRetryContract(
  input: MutationRetryContractInput,
): MutationRetryContract {
  const auditId = textValue(input?.auditId);
  if (!RETRY_AUDIT_ID_PATTERN.test(auditId)) {
    throw new TypeError("Mutation retry requires a versioned audit id.");
  }
  const approved = APPROVED_MUTATION_RETRY_CONTRACTS.get(auditId);
  if (!approved) {
    throw new TypeError("Mutation retry audit id is absent from the approved audit registry.");
  }
  const requestedTarget = {
    action: textValue(input.action),
    endpoint: textValue(input.endpoint),
    method: normalizedMethod(input.method),
  };
  if (!sameMutationTarget(requestedTarget, approved)) {
    throw new TypeError("Mutation retry audit id does not match the approved mutation target (method, endpoint, and action).");
  }
  const idempotencyKey = textValue(input.idempotencyKey);
  const requestFingerprint = textValue(input.requestFingerprint);
  if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)
      || !SHA256_FINGERPRINT_PATTERN.test(requestFingerprint)) {
    throw new TypeError("Mutation retry requires a stable Idempotency-Key and canonical SHA-256 request fingerprint.");
  }
  const contract: MutationRetryContract = Object.freeze({
    [MUTATION_RETRY_CONTRACT_BRAND]: true as const,
    action: approved.action,
    auditId,
    endpoint: approved.endpoint,
    idempotencyKey,
    method: approved.method,
    requestFingerprint,
    serverDeduplicates: true,
  });
  ISSUED_MUTATION_RETRY_CONTRACTS.add(contract);
  return contract;
}

export function idempotencyHeaders(contract: MutationRetryContract): Record<string, string> {
  validateIssuedMutationContract(contract);
  return { "Idempotency-Key": contract.idempotencyKey };
}

export function validateMutationContract(
  method: string,
  endpoint: string | undefined,
  action: string | undefined,
  contract: MutationRetryContract | undefined,
): void {
  if (!contract) return;
  validateIssuedMutationContract(contract);
  const operationMethod = normalizedMethod(method);
  if (operationMethod !== contract.method) {
    throw new TypeError("Mutation retry method differs from its approved audit registry target.");
  }
  if (textValue(endpoint) !== contract.endpoint) {
    throw new TypeError("Mutation retry endpoint differs from its approved audit registry target.");
  }
  if (textValue(action) !== contract.action) {
    throw new TypeError("Mutation retry action differs from its approved audit registry target.");
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

function approvedMutationRetryContracts(): ReadonlyMap<string, MutationRetryTarget> {
  const registry = mutationRetryRegistry as unknown as Record<string, unknown>;
  const values = registry.contracts;
  if (registry.schema !== MUTATION_RETRY_REGISTRY_SCHEMA || !Array.isArray(values)) {
    return new Map();
  }
  const approved = new Map<string, MutationRetryTarget>();
  for (const value of values) {
    const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
    const auditId = textValue(record.audit_id);
    const target = {
      action: textValue(record.action),
      endpoint: textValue(record.endpoint),
      method: normalizedMethod(record.method),
    };
    if (!RETRY_AUDIT_ID_PATTERN.test(auditId)
        || approved.has(auditId)
        || !validMutationTarget(target)) {
      return new Map();
    }
    approved.set(auditId, Object.freeze(target));
  }
  return approved.size === values.length ? approved : new Map();
}

function validateIssuedMutationContract(contract: MutationRetryContract): void {
  if (!contract || typeof contract !== "object" || !ISSUED_MUTATION_RETRY_CONTRACTS.has(contract)) {
    throw new TypeError("Mutation retry contract must be factory-issued by createMutationRetryContract().");
  }
  const approved = APPROVED_MUTATION_RETRY_CONTRACTS.get(contract.auditId);
  if (!approved
      || contract[MUTATION_RETRY_CONTRACT_BRAND] !== true
      || contract.serverDeduplicates !== true
      || !sameMutationTarget(contract, approved)
      || !IDEMPOTENCY_KEY_PATTERN.test(contract.idempotencyKey)
      || !SHA256_FINGERPRINT_PATTERN.test(contract.requestFingerprint)) {
    throw new TypeError("Mutation retry contract is not a valid approved factory contract.");
  }
}

function sameMutationTarget(left: MutationRetryTarget, right: MutationRetryTarget): boolean {
  return left.method === right.method && left.endpoint === right.endpoint && left.action === right.action;
}

function validMutationTarget(target: MutationRetryTarget): boolean {
  return MUTATION_METHODS.has(target.method)
    && MUTATION_ENDPOINT_PATTERN.test(target.endpoint)
    && MUTATION_ACTION_PATTERN.test(target.action);
}

function normalizedMethod(value: unknown): string {
  return textValue(value).toUpperCase();
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function isAbortError(error: unknown): boolean {
  return error instanceof RetryCancelledError
    || (Boolean(error) && typeof error === "object" && (error as { name?: unknown }).name === "AbortError");
}

function finiteDelay(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}
