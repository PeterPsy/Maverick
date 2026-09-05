import { describeReadModelRequest } from "./readModelRequest";
import type { ReadModelRequest } from "./readModelRetry";
import { executeRetryJsonRequest, retryAfterMilliseconds } from "./retryJsonRequest";

const SAFE_REQUEST_RETRY_EXECUTOR_BRAND: unique symbol = Symbol("maverick.safe-request-retry-executor");
const SAFE_ENDPOINT_PATTERN = /^\/api\/[^\s#]{1,506}$/u;
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const ISSUED_SAFE_REQUEST_RETRY_EXECUTORS = new WeakSet<object>();

export type SafeRequestRetryExecutorInput = Readonly<{
  endpoint: string;
  method?: string;
}>;

export type SafeRequestRetryExecutor = Readonly<{
  [SAFE_REQUEST_RETRY_EXECUTOR_BRAND]: true;
  body?: string;
  etag?: string;
  endpoint: string;
  method: string;
}>;

export class SafeRequestRetryHttpError extends Error {
  readonly response: Response;
  readonly retryAfterMs: number | undefined;
  readonly status: number;

  constructor(response: Response) {
    super(`Safe request failed with HTTP ${response.status}.`);
    this.name = "SafeRequestRetryHttpError";
    this.response = response;
    this.status = response.status;
    this.retryAfterMs = retryAfterMilliseconds(response.headers.get("retry-after"));
  }
}

export class SafeRequestRetryTransportError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "MaverickTransportError";
  }
}

export function createSafeRequestRetryExecutor(
  input: SafeRequestRetryExecutorInput,
): SafeRequestRetryExecutor {
  const endpoint = typeof input?.endpoint === "string" ? input.endpoint : "";
  const method = typeof input?.method === "string" ? input.method.trim().toUpperCase() : "GET";
  if (!SAFE_ENDPOINT_PATTERN.test(endpoint)) {
    throw new TypeError("Safe request retry requires one bounded relative /api/ endpoint.");
  }
  if (!SAFE_METHODS.has(method)) {
    throw new TypeError("Safe request retry accepts only GET, HEAD, or OPTIONS.");
  }
  const executor: SafeRequestRetryExecutor = Object.freeze({
    [SAFE_REQUEST_RETRY_EXECUTOR_BRAND]: true as const,
    endpoint,
    method,
  });
  ISSUED_SAFE_REQUEST_RETRY_EXECUTORS.add(executor);
  return executor;
}

/** Issue a concrete read only from the SDK's closed, reviewed app/resource descriptors. */
export function createReadModelRequestExecutor(request: ReadModelRequest): SafeRequestRetryExecutor {
  const descriptor = describeReadModelRequest(request);
  const etag = request.etag;
  if (etag !== undefined && (typeof etag !== "string" || etag.length > 512 || /[\r\n]/u.test(etag))) {
    throw new TypeError("Invalid read-model validator.");
  }
  const executor: SafeRequestRetryExecutor = Object.freeze({
    [SAFE_REQUEST_RETRY_EXECUTOR_BRAND]: true as const,
    ...descriptor,
    ...(etag ? { etag } : {}),
    method: descriptor.body === undefined ? "GET" : "POST",
  });
  ISSUED_SAFE_REQUEST_RETRY_EXECUTORS.add(executor);
  return executor;
}

export function validateSafeRequestRetryExecutor(executor: SafeRequestRetryExecutor): void {
  if (!executor
      || typeof executor !== "object"
      || !ISSUED_SAFE_REQUEST_RETRY_EXECUTORS.has(executor)
      || executor[SAFE_REQUEST_RETRY_EXECUTOR_BRAND] !== true
      || !SAFE_ENDPOINT_PATTERN.test(executor.endpoint)
      || (!SAFE_METHODS.has(executor.method) && !(executor.method === "POST" && executor.body !== undefined))) {
    throw new TypeError(
      "Safe request retry executor must be factory-issued by createSafeRequestRetryExecutor().",
    );
  }
}

export async function executeSafeRequestRetryExecutor(
  executor: SafeRequestRetryExecutor,
  signal: AbortSignal,
): Promise<unknown> {
  validateSafeRequestRetryExecutor(executor);
  return executeRetryJsonRequest({
    body: executor.body,
    endpoint: executor.endpoint,
    etag: executor.etag,
    headers: { Accept: "application/json", ...(executor.body ? { "Content-Type": "application/json" } : {}), ...(executor.etag ? { "If-None-Match": executor.etag } : {}) },
    httpError: SafeRequestRetryHttpError,
    label: "Safe",
    method: executor.method,
    transportError: SafeRequestRetryTransportError,
  }, signal);
}
