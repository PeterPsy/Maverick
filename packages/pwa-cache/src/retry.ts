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
  createRequestFingerprint,
  idempotencyHeaders,
} from "./retryPolicy";
export type {
  MutationRetryContract,
  RetryClassification,
  RetryCoordinatorOptions,
  RetryDisposition,
  RetryOperationOptions,
  RetryTelemetryEvent,
} from "./retryPolicy";

type PendingFlight = {
  controller: AbortController;
  promise: Promise<unknown>;
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
    validateMutationContract(method, options.mutation);
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
    const flight: PendingFlight = { controller, promise: Promise.resolve(undefined), wake: null };
    const promise = this.execute(options, method, flight, operationKey)
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
    for (const [key, flight] of this.flights) {
      this.telemetry({ attempt: 0, keyHash: this.telemetryHash(key), kind: "cancelled" });
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
    operationKey: string,
  ): Promise<T> {
    let attempt = 0;
    let lastAttemptAt = Number.NEGATIVE_INFINITY;
    const keyHash = this.telemetryHash(operationKey);
    while (true) {
      throwIfAborted(flight.controller.signal);
      lastAttemptAt = this.now();
      if (attempt > 0) {
        this.telemetry({ attempt, keyHash, kind: "retry_attempt" });
      }
      try {
        const result = await options.operation({ attempt, signal: flight.controller.signal });
        throwIfAborted(flight.controller.signal);
        this.telemetry({ attempt, keyHash, kind: "resolved" });
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
        this.telemetry({ attempt, keyHash, kind: "wait_started", waitMs: delay });
        await this.waitForRetry(flight, Math.max(delay, this.minRetryIntervalMs - (this.now() - lastAttemptAt)));
        attempt += 1;
      }
    }
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
      const idempotencyScope = JSON.stringify([this.scopeKey, method, mutation.idempotencyKey]);
      const knownFingerprint = this.mutationFingerprints.get(idempotencyScope);
      if (knownFingerprint && knownFingerprint !== mutation.requestFingerprint) {
        throw new TypeError("An Idempotency-Key cannot be reused with a different request fingerprint.");
      }
      this.mutationFingerprints.set(idempotencyScope, mutation.requestFingerprint);
      trimOldestStringMap(this.mutationFingerprints, 1_024);
      return JSON.stringify([
        this.scopeKey,
        "idempotent-mutation",
        method,
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
