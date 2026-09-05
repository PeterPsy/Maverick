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
  validateMutationContract,
  validateOperationKey,
  type RetryCoordinatorOptions,
  type RetryOperationOptions,
  type RetryTelemetryEvent,
} from "./retryPolicy";
import { RetryVisibilityMonitor } from "./retryVisibility";

export {
  RetryCancelledError,
  classifyRetryError,
  createIdempotencyKey,
  createMutationRetryContract,
  createRequestFingerprint,
  idempotencyHeaders,
} from "./retryPolicy";
export type {
  MutationRetryContract,
  MutationRetryContractInput,
  MutationRetryTarget,
  RetryClassification,
  RetryCoordinatorOptions,
  RetryDisposition,
  RetryOperationOptions,
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

  run<T>(options: RetryOperationOptions<T>): Promise<T> {
    this.start();
    const method = (options.method ?? "GET").trim().toUpperCase();
    const operationKey = validateOperationKey(options.key);
    validateMutationContract(method, options.endpoint, options.action, options.mutation);
    const flightKey = this.flightKey(method, operationKey, options.mutation);
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
    const promise = this.execute(options, method, flight)
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

  private async execute<T>(
    options: RetryOperationOptions<T>,
    method: string,
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
          const classification = (options.classify ?? classifyRetryError)(error);
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
            && (SAFE_METHODS.has(method) || Boolean(options.mutation));
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
    mutation: RetryOperationOptions<unknown>["mutation"],
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
    if (!SAFE_METHODS.has(method)) {
      this.flightSequence += 1;
      return JSON.stringify([this.scopeKey, "uncoordinated-mutation", method, operationKey, this.flightSequence]);
    }
    return JSON.stringify([this.scopeKey, "read", method, operationKey]);
  }

  private telemetryHash(value: string): string {
    return stableHash(`${this.telemetrySalt}:${value}`);
  }
}
