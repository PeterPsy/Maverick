import {
  mutationRetryRequestBody,
  type MutationRetryExecutor,
} from "./mutationRetry";
import { executeRetryJsonRequest, retryAfterMilliseconds } from "./retryJsonRequest";

export class MutationRetryHttpError extends Error {
  readonly response: Response;
  readonly retryAfterMs: number | undefined;
  readonly status: number;

  constructor(response: Response) {
    super(`Mutation request failed with HTTP ${response.status}.`);
    this.name = "MutationRetryHttpError";
    this.response = response;
    this.status = response.status;
    this.retryAfterMs = retryAfterMilliseconds(response.headers.get("retry-after"));
  }
}

export class MutationRetryTransportError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "MaverickTransportError";
  }
}

export async function executeMutationRetryExecutor(
  executor: MutationRetryExecutor,
  signal: AbortSignal,
): Promise<unknown> {
  const body = mutationRetryRequestBody(executor);
  return executeRetryJsonRequest({
    body,
    endpoint: executor.endpoint,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": executor.idempotencyKey,
    },
    httpError: MutationRetryHttpError,
    label: "Mutation",
    method: executor.method,
    transportError: MutationRetryTransportError,
  }, signal);
}
