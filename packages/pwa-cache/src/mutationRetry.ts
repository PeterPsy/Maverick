import mutationRetryRegistry from "./mutationRetryRegistry.v2.json";

const MUTATION_RETRY_EXECUTOR_BRAND: unique symbol = Symbol("maverick.mutation-retry-executor");
const MUTATION_RETRY_REGISTRY_SCHEMA = "maverick.pwa-mutation-retry-registry.v2";
const MUTATION_RETRY_MAX_BODY_BYTES = 1_048_576;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{15,199}$/u;
const RETRY_AUDIT_ID_PATTERN = /^[a-z0-9][a-z0-9.-]{4,126}\.v[1-9][0-9]*$/u;
const MUTATION_ACTION_PATTERN = /^[a-z0-9][a-z0-9._:-]{1,127}$/u;
const MUTATION_ENDPOINT_PATTERN = /^\/api\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,506}$/u;
const MUTATION_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type MutationRetryTarget = Readonly<{
  action: string;
  endpoint: string;
  method: string;
}>;

export type MutationRetryExecutorInput = MutationRetryTarget & Readonly<{
  auditId: string;
  idempotencyKey: string;
  request: Readonly<Record<string, unknown>>;
}>;

export type MutationRetryExecutor = MutationRetryTarget & Readonly<{
  [MUTATION_RETRY_EXECUTOR_BRAND]: true;
  auditId: string;
  idempotencyKey: string;
  requestFingerprint: string;
  serverDeduplicates: true;
}>;

type MutationRetryExecutorState = Readonly<{
  body: string;
}>;

const APPROVED_MUTATION_RETRY_CONTRACTS = approvedMutationRetryContracts();
export const APPROVED_MUTATION_RETRY_AUDIT_IDS = Object.freeze([
  ...APPROVED_MUTATION_RETRY_CONTRACTS.keys(),
]);
const ISSUED_MUTATION_RETRY_EXECUTORS = new WeakMap<object, MutationRetryExecutorState>();

export function createIdempotencyKey(prefix = "mvr"): string {
  const normalizedPrefix = prefix.replace(/[^A-Za-z0-9]/g, "").slice(0, 16) || "mvr";
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${normalizedPrefix}:${random}`;
}

export async function createRequestFingerprint(serializedRequest: string): Promise<string> {
  if (typeof serializedRequest !== "string" || !serializedRequest.length) {
    throw new TypeError("Mutation retry request fingerprint input is required.");
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error("SHA-256 is unavailable; this mutation cannot be retried safely.");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(serializedRequest),
  );
  return `sha256:${Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("")}`;
}

/**
 * Issue an executor for one reviewed JSON mutation.
 *
 * The caller supplies request semantics, never a transport callback. The SDK
 * validates and snapshots those semantics, derives the fingerprint, appends
 * the deduplication fields, and owns the exact fetch target/method/headers used
 * for every attempt.
 */
export async function createMutationRetryExecutor(
  input: MutationRetryExecutorInput,
): Promise<MutationRetryExecutor> {
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
    throw new TypeError(
      "Mutation retry audit id does not match the approved mutation target (method, endpoint, and action).",
    );
  }
  const idempotencyKey = textValue(input.idempotencyKey);
  if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
    throw new TypeError("Mutation retry requires a stable Idempotency-Key.");
  }
  if (!isJsonValue(input.request, new Set()) || Array.isArray(input.request) || input.request === null) {
    throw new TypeError("Mutation retry request must be an exact JSON object.");
  }
  const serializedRequest = JSON.stringify(input.request);
  if (new TextEncoder().encode(serializedRequest).byteLength > MUTATION_RETRY_MAX_BODY_BYTES) {
    throw new TypeError("Mutation retry JSON request exceeds the SDK body limit.");
  }
  const requestSnapshot = JSON.parse(serializedRequest) as Record<string, unknown>;
  assertExactJsonRequest(requestSnapshot, approved.action);
  const requestFingerprint = await createRequestFingerprint(serializedRequest);
  const body = JSON.stringify({
    ...requestSnapshot,
    idempotency_key: idempotencyKey,
    request_fingerprint: requestFingerprint,
  });
  const executor: MutationRetryExecutor = Object.freeze({
    [MUTATION_RETRY_EXECUTOR_BRAND]: true as const,
    action: approved.action,
    auditId,
    endpoint: approved.endpoint,
    idempotencyKey,
    method: approved.method,
    requestFingerprint,
    serverDeduplicates: true,
  });
  ISSUED_MUTATION_RETRY_EXECUTORS.set(executor, Object.freeze({ body }));
  return executor;
}

export function validateMutationRetryExecutor(
  executor: MutationRetryExecutor,
): void {
  const state = executor && typeof executor === "object"
    ? ISSUED_MUTATION_RETRY_EXECUTORS.get(executor)
    : undefined;
  if (!state) {
    throw new TypeError(
      "Mutation retry executor must be factory-issued by createMutationRetryExecutor().",
    );
  }
  const approved = APPROVED_MUTATION_RETRY_CONTRACTS.get(executor.auditId);
  if (!approved
      || executor[MUTATION_RETRY_EXECUTOR_BRAND] !== true
      || executor.serverDeduplicates !== true
      || !sameMutationTarget(executor, approved)
      || !IDEMPOTENCY_KEY_PATTERN.test(executor.idempotencyKey)) {
    throw new TypeError("Mutation retry executor is not a valid approved factory executor.");
  }
}

export function mutationRetryRequestBody(
  executor: MutationRetryExecutor,
): string {
  validateMutationRetryExecutor(executor);
  return ISSUED_MUTATION_RETRY_EXECUTORS.get(executor)?.body as string;
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

function assertExactJsonRequest(value: unknown, approvedAction: string): asserts value is Record<string, unknown> {
  if (!isJsonValue(value, new Set()) || Array.isArray(value) || value === null) {
    throw new TypeError("Mutation retry request must be an exact JSON object.");
  }
  const request = value as Record<string, unknown>;
  if (request.action !== approvedAction) {
    throw new TypeError("Mutation retry JSON action differs from its approved registry target.");
  }
  if (Object.hasOwn(request, "idempotency_key") || Object.hasOwn(request, "request_fingerprint")) {
    throw new TypeError("Mutation retry deduplication fields are SDK-owned.");
  }
}

function isJsonValue(value: unknown, ancestors: Set<object>): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return true;
  }
  if (typeof value === "number") {
    return Number.isFinite(value);
  }
  if (typeof value !== "object") {
    return false;
  }
  if (ancestors.has(value)) {
    return false;
  }
  ancestors.add(value);
  let valid: boolean;
  if (Array.isArray(value)) {
    const ownKeys = Reflect.ownKeys(value);
    valid = ownKeys.every((key) => (
      key === "length"
      || (typeof key === "string" && /^(0|[1-9][0-9]*)$/u.test(key) && Number(key) < value.length)
    ));
    for (let index = 0; valid && index < value.length; index += 1) {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      valid = Boolean(descriptor
        && descriptor.enumerable
        && Object.hasOwn(descriptor, "value")
        && isJsonValue(descriptor.value, ancestors));
    }
  } else {
    const prototype = Object.getPrototypeOf(value);
    const descriptors = Object.getOwnPropertyDescriptors(value);
    valid = (prototype === Object.prototype || prototype === null)
      && Reflect.ownKeys(value).every((key) => {
        if (typeof key !== "string") return false;
        const descriptor = descriptors[key];
        return Boolean(descriptor
          && descriptor.enumerable
          && Object.hasOwn(descriptor, "value")
          && isJsonValue(descriptor.value, ancestors));
      });
  }
  ancestors.delete(value);
  return valid;
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
