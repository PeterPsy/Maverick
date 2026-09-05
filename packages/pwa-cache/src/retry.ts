import {
  RetryCancelledError,
  SAFE_METHODS,
  cancellationFromSignal,
  clamp,
  classifyRetryError,
  createTelemetrySalt,
  positive,
  stableHash,
  throwIfAborted,
  trimOldestStringMap,
  validateOperationKey,
  type MutationRetryOperationOptions,
  type OpaqueRetryOperationOptions,
  type RetryClassification,
  type RetryCoordinatorOptions,
  type SafeRequestRetryOperationOptions,
  type RetryTelemetryEvent,
} from "./retryPolicy";
import { RetryVisibilityMonitor } from "./retryVisibility";
import {
  validateMutationRetryExecutor,
  type MutationRetryExecutor,
} from "./mutationRetry";
import { executeMutationRetryExecutor } from "./mutationRetryRequest";
import {
  SafeRequestRetryHttpError,
  SafeRequestRetryTransportError,
  createSafeRequestRetryExecutor,
  executeSafeRequestRetryExecutor,
  validateSafeRequestRetryExecutor,
  type SafeRequestRetryExecutor,
} from "./safeRequestRetry";

export {
  createIdempotencyKey,
  createMutationRetryExecutor,
  createRequestFingerprint,
} from "./mutationRetry";
export {
  MutationRetryHttpError,
  MutationRetryTransportError,
} from "./mutationRetryRequest";
export {
  SafeRequestRetryHttpError,
  SafeRequestRetryTransportError,
  createSafeRequestRetryExecutor,
} from "./safeRequestRetry";
export type {
  MutationRetryExecutor,
  MutationRetryExecutorInput,
  MutationRetryTarget,
} from "./mutationRetry";
export type {
  SafeRequestRetryExecutor,
  SafeRequestRetryExecutorInput,
} from "./safeRequestRetry";
export {
  RetryCancelledError,
  classifyRetryError,
} from "./retryPolicy";
export type {
  MutationRetryOperationOptions,
  OpaqueRetryOperationOptions,
  RetryClassification,
  RetryCoordinatorOptions,
  RetryDisposition,
  SafeRequestRetryOperationOptions,
  RetryTelemetryEvent,
} from "./retryPolicy";

type PendingFlight = {
  attempt: number;
  completionReported: boolean;
  controller: AbortController;
  keyHash: string;
  promise: Promise<unknown>;
  waitStartedAt: number | null;
  wake: (() => void) | null;
};

type CoordinatedOperation<T> = {
  classify: (error: unknown) => RetryClassification;
  method: string;
  mutation?: MutationRetryExecutor;
  operation: (context: { attempt: number; signal: AbortSignal }) => Promise<T>;
  operationKey: string;
  safeRequest?: SafeRequestRetryExecutor;
  signal?: AbortSignal;
};

export class RetryCoordinator {
  private readonly baseDelayMs: number;
  private readonly capDelayMs: number;
  private readonly clearTimer: (timer: unknown) => void;
  private readonly maxMutationAttempts: number;
  private readonly minRetryIntervalMs: number;
  private readonly now: () => number;
  private readonly random: () => number;
  private readonly setTimer: (callback: () => void, delayMs: number) => unknown;
  private readonly telemetry: (event: RetryTelemetryEvent) => void;
  private readonly visibility: RetryVisibilityMonitor;
  private readonly flights = new Map<string, PendingFlight>();
  private readonly mutationFingerprints = new Map<string, string>();
  private readonly telemetrySalt = createTelemetrySalt();
  private flightSequence = 0;
  private scopeKey = "initial";

  constructor(options: RetryCoordinatorOptions = {}) {
    this.baseDelayMs = positive(options.baseDelayMs, 1_000);
    this.capDelayMs = positive(options.capDelayMs, 30_000);
    this.minRetryIntervalMs = positive(options.minRetryIntervalMs, 250);
    this.maxMutationAttempts = Math.max(1, Math.floor(positive(options.maxMutationAttempts, 3)));
    this.now = options.now ?? Date.now;
    this.random = options.random ?? Math.random;
    this.setTimer = options.setTimer ?? ((callback, delay) => globalThis.setTimeout(callback, delay));
    this.clearTimer = options.clearTimer ?? ((timer) => globalThis.clearTimeout(timer as ReturnType<typeof setTimeout>));
    this.telemetry = options.telemetry ?? (() => undefined);
    this.visibility = new RetryVisibilityMonitor(
      options.isVisible ?? (() => typeof document === "undefined" || document.visibilityState !== "hidden"),
      () => this.hint(),
    );
  }

  start(): void {
    this.visibility.start();
  }

  runOpaque<T>(options: OpaqueRetryOperationOptions<T>): Promise<T> {
    rejectRetryFieldsOnOpaqueOperation(options);
    this.start();
    const operationKey = validateOperationKey(options.key);
    return this.#coordinate({
      classify: classifyRetryError,
      method: "OPAQUE",
      operation: options.operation,
      operationKey,
      signal: options.signal,
    });
  }

  runRequest<T = unknown>(options: SafeRequestRetryOperationOptions): Promise<T> {
    rejectOpaqueFieldsOnSafeRequestOperation(options);
    this.start();
    const operationKey = validateOperationKey(options.key);
    const executor = options.executor;
    validateSafeRequestRetryExecutor(executor);
    return this.#coordinate({
      classify: classifyRetryError,
      method: executor.method,
      operation: ({ signal }) => executeSafeRequestRetryExecutor(executor, signal) as Promise<T>,
      operationKey,
      safeRequest: executor,
      signal: options.signal,
    });
  }

  runMutation<T = unknown>(options: MutationRetryOperationOptions): Promise<T> {
    rejectOpaqueFieldsOnMutationOperation(options);
    this.start();
    const operationKey = validateOperationKey(options.key);
    const executor = options.executor;
    validateMutationRetryExecutor(executor);
    return this.#coordinate({
      classify: classifyRetryError,
      method: executor.method,
      mutation: executor,
      operation: ({ signal }) => executeMutationRetryExecutor(executor, signal) as Promise<T>,
      operationKey,
      signal: options.signal,
    });
  }

  #coordinate<T>(options: CoordinatedOperation<T>): Promise<T> {
    const flightKey = this.flightKey(
      options.method,
      options.operationKey,
      options.mutation,
      options.safeRequest,
    );
    const existing = this.flights.get(flightKey)?.promise as Promise<T> | undefined;
    if (existing) {
      return existing;
    }

    const controller = new AbortController();
    const relayAbort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) {
      relayAbort();
    } else {
      options.signal?.addEventListener("abort", relayAbort, { once: true });
    }
    const flight: PendingFlight = {
      attempt: 0,
      completionReported: false,
      controller,
      keyHash: this.telemetryHash(flightKey),
      promise: Promise.resolve(undefined),
      waitStartedAt: null,
      wake: null,
    };
    const promise = this.#execute(options, flight)
      .finally(() => {
        options.signal?.removeEventListener("abort", relayAbort);
        if (this.flights.get(flightKey) === flight) {
          this.flights.delete(flightKey);
        }
      });
    flight.promise = promise;
    this.flights.set(flightKey, flight);
    return promise;
  }

  confirmUsefulTransport(): void {
    this.hint();
  }

  hint(): void {
    if (!this.visibility.visible()) {
      return;
    }
    for (const flight of this.flights.values()) {
      flight.wake?.();
    }
  }

  setClientVisibility(visible: boolean): void {
    this.visibility.setClientVisibility(visible);
  }

  setScope(scopeKey: string): void {
    const normalized = scopeKey.trim() || "anonymous";
    if (normalized === this.scopeKey) {
      return;
    }
    this.cancelAll("Retry scope changed.");
    this.mutationFingerprints.clear();
    this.scopeKey = normalized;
  }

  cancelAll(reason = "Retry operations were cancelled."): void {
    for (const flight of this.flights.values()) {
      this.reportCompletion(flight, "cancelled");
      flight.controller.abort(new RetryCancelledError(reason));
      flight.wake?.();
    }
  }

  pendingCount(): number {
    return this.flights.size;
  }

  dispose(): void {
    this.cancelAll("Retry coordinator disposed.");
    this.mutationFingerprints.clear();
    this.visibility.dispose();
  }

  async #execute<T>(
    options: CoordinatedOperation<T>,
    flight: PendingFlight,
  ): Promise<T> {
    let attempt = 0;
    let lastAttemptAt = Number.NEGATIVE_INFINITY;
    try {
      while (true) {
        throwIfAborted(flight.controller.signal);
        flight.attempt = attempt;
        lastAttemptAt = this.now();
        if (attempt > 0) {
          this.telemetry({ attempt, keyHash: flight.keyHash, kind: "retry_attempt" });
        }
        try {
          const result = await options.operation({ attempt, signal: flight.controller.signal });
          throwIfAborted(flight.controller.signal);
          this.reportCompletion(flight, "resolved");
          return result;
        } catch (error) {
          const classification = options.classify(error);
          if (classification.disposition === "terminal") {
            throw error;
          }
          if (flight.controller.signal.aborted) {
            throw cancellationFromSignal(flight.controller.signal);
          }
          if (classification.disposition === "cancelled") {
            throw new RetryCancelledError();
          }
          const canRetry = classification.disposition === "retryable"
            && (SAFE_METHODS.has(options.method) || Boolean(options.mutation));
          if (!canRetry || (options.mutation && attempt + 1 >= this.maxMutationAttempts)) {
            throw error;
          }
          const delay = this.retryDelay(attempt, classification.retryAfterMs);
          if (flight.waitStartedAt === null) {
            flight.waitStartedAt = this.now();
            this.telemetry({ attempt, keyHash: flight.keyHash, kind: "wait_started", waitMs: delay });
          }
          await this.waitForRetry(flight, Math.max(delay, this.minRetryIntervalMs - (this.now() - lastAttemptAt)));
          attempt += 1;
        }
      }
    } catch (error) {
      if (flight.controller.signal.aborted || error instanceof RetryCancelledError) {
        this.reportCompletion(flight, "cancelled");
      } else if (flight.waitStartedAt !== null) {
        this.reportCompletion(flight, "resolved");
      }
      throw error;
    }
  }

  private reportCompletion(flight: PendingFlight, kind: "cancelled" | "resolved"): void {
    if (flight.completionReported) return;
    flight.completionReported = true;
    const durationMs = flight.waitStartedAt === null
      ? undefined
      : Math.max(0, this.now() - flight.waitStartedAt);
    this.telemetry({
      attempt: flight.attempt,
      ...(durationMs === undefined ? {} : { durationMs }),
      keyHash: flight.keyHash,
      kind,
    });
  }

  private retryDelay(attempt: number, retryAfterMs: number | undefined): number {
    const exponential = Math.min(this.capDelayMs, this.baseDelayMs * (2 ** Math.min(attempt, 30)));
    const jitter = 0.75 + clamp(this.random(), 0, 1) * 0.5;
    const retryAfter = Number.isFinite(retryAfterMs) ? Math.max(0, retryAfterMs as number) : 0;
    return Math.max(Math.round(exponential * jitter), retryAfter);
  }

  private waitForRetry(flight: PendingFlight, delayMs: number): Promise<void> {
    return new Promise((resolve, reject) => {
      let timer: unknown;
      let settled = false;
      const notBefore = this.now() + this.minRetryIntervalMs;
      const finish = () => {
        if (settled) {
          return;
        }
        settled = true;
        if (timer !== undefined) {
          this.clearTimer(timer);
        }
        flight.wake = null;
        flight.controller.signal.removeEventListener("abort", abort);
        resolve();
      };
      const scheduledWake = () => {
        timer = undefined;
        if (!this.visibility.visible()) {
          return;
        }
        finish();
      };
      const hintedWake = () => {
        const remaining = notBefore - this.now();
        if (remaining <= 0) {
          finish();
          return;
        }
        if (timer !== undefined) {
          this.clearTimer(timer);
        }
        timer = this.setTimer(scheduledWake, remaining);
      };
      const abort = () => {
        if (settled) {
          return;
        }
        settled = true;
        if (timer !== undefined) {
          this.clearTimer(timer);
        }
        flight.wake = null;
        reject(cancellationFromSignal(flight.controller.signal));
      };
      flight.wake = hintedWake;
      flight.controller.signal.addEventListener("abort", abort, { once: true });
      if (this.visibility.visible()) {
        timer = this.setTimer(scheduledWake, Math.max(0, delayMs));
      }
    });
  }

  private flightKey(
    method: string,
    operationKey: string,
    mutation: MutationRetryExecutor | undefined,
    safeRequest: SafeRequestRetryExecutor | undefined,
  ): string {
    if (mutation) {
      const idempotencyScope = JSON.stringify([
        this.scopeKey,
        mutation.auditId,
        method,
        mutation.endpoint,
        mutation.action,
        mutation.idempotencyKey,
      ]);
      const knownFingerprint = this.mutationFingerprints.get(idempotencyScope);
      if (knownFingerprint && knownFingerprint !== mutation.requestFingerprint) {
        throw new TypeError("An Idempotency-Key cannot be reused with a different request fingerprint.");
      }
      this.mutationFingerprints.set(idempotencyScope, mutation.requestFingerprint);
      trimOldestStringMap(this.mutationFingerprints, 1_024);
      return JSON.stringify([
        this.scopeKey,
        "idempotent-mutation",
        mutation.auditId,
        method,
        mutation.endpoint,
        mutation.action,
        mutation.idempotencyKey,
        mutation.requestFingerprint,
      ]);
    }
    if (safeRequest) {
      return JSON.stringify([
        this.scopeKey,
        "read",
        method,
        safeRequest.endpoint,
        operationKey,
      ]);
    }
    if (!SAFE_METHODS.has(method)) {
      this.flightSequence += 1;
      return JSON.stringify([this.scopeKey, "opaque", method, operationKey, this.flightSequence]);
    }
    throw new TypeError("Retryable safe requests require an SDK-owned request executor.");
  }

  private telemetryHash(value: string): string {
    return stableHash(`${this.telemetrySalt}:${value}`);
  }
}

function rejectRetryFieldsOnOpaqueOperation(options: OpaqueRetryOperationOptions<unknown>): void {
  const record = options as unknown as Record<string, unknown>;
  if (["action", "classify", "endpoint", "executor", "method", "mutation"]
    .some((field) => Object.hasOwn(record, field))) {
    throw new TypeError(
      "RetryCoordinator.runOpaque() is one-shot and cannot accept request or retry metadata.",
    );
  }
}

function rejectOpaqueFieldsOnSafeRequestOperation(options: SafeRequestRetryOperationOptions): void {
  const record = options as unknown as Record<string, unknown>;
  if (["action", "classify", "endpoint", "method", "mutation", "operation"]
    .some((field) => Object.hasOwn(record, field))) {
    throw new TypeError(
      "RetryCoordinator.runRequest() accepts only the SDK-owned safe request executor.",
    );
  }
}

function rejectOpaqueFieldsOnMutationOperation(options: MutationRetryOperationOptions): void {
  const record = options as unknown as Record<string, unknown>;
  if (["action", "classify", "endpoint", "method", "mutation", "operation"]
    .some((field) => Object.hasOwn(record, field))) {
    throw new TypeError(
      "RetryCoordinator.runMutation() accepts only the SDK-owned mutation executor.",
    );
  }
}
