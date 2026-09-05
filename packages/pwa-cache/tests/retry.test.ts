import { afterEach, describe, expect, it, vi } from "vitest";
import {
  RetryCancelledError,
  RetryCoordinator,
  createIdempotencyKey,
  createMutationRetryContract,
  createRequestFingerprint,
  idempotencyHeaders,
  type MutationRetryContract,
} from "../src";

function transportError(): Error {
  return Object.assign(new Error("transport"), { name: "MaverickTransportError" });
}

function fingerprint(hexDigit = "a"): string {
  return `sha256:${hexDigit.repeat(64)}`;
}

const TEST_RETRY_AUDIT_ID = "base-shell.pinned-apps.set.v1";
const TEST_MUTATION_TARGET = {
  action: "pinned_apps.set",
  endpoint: "/api/apps/app-store/backend",
  method: "POST",
} as const;

function approvedMutation(
  idempotencyKey = createIdempotencyKey(),
  requestFingerprint = fingerprint(),
): MutationRetryContract {
  return createMutationRetryContract({
    auditId: TEST_RETRY_AUDIT_ID,
    ...TEST_MUTATION_TARGET,
    idempotencyKey,
    requestFingerprint,
  });
}

describe("RAM retry coordinator", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries idempotent reads with capped exponential delay and single flight", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const operation = vi.fn(async ({ attempt }: { attempt: number }) => {
      if (attempt < 2) throw transportError();
      return "ok";
    });
    const first = coordinator.run({ key: "shell:session", operation });
    const second = coordinator.run({ key: "shell:session", operation });
    expect(first).toBe(second);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(first).resolves.toBe("ok");
    expect(operation).toHaveBeenCalledTimes(3);
  });

  it("reports one bounded wait lifecycle across retries", async () => {
    vi.useFakeTimers();
    const telemetry: Array<Record<string, unknown>> = [];
    const coordinator = new RetryCoordinator({
      random: () => 0.5,
      telemetry: (event) => telemetry.push(event),
    });
    const operation = vi.fn()
      .mockRejectedValueOnce(transportError())
      .mockRejectedValueOnce(transportError())
      .mockResolvedValueOnce("ok");
    const pending = coordinator.run({ key: "read:observed", operation });

    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(pending).resolves.toBe("ok");
    expect(telemetry.map((event) => event.kind)).toEqual([
      "wait_started",
      "retry_attempt",
      "retry_attempt",
      "resolved",
    ]);
    expect(telemetry.at(-1)).toMatchObject({ attempt: 2, durationMs: 3_000 });
    expect(new Set(telemetry.map((event) => event.keyHash))).toHaveLength(1);
  });

  it("treats 401, 403, 409, and 422 as terminal", async () => {
    for (const status of [401, 403, 409, 422]) {
      const coordinator = new RetryCoordinator();
      const error = Object.assign(new Error(String(status)), { status });
      const operation = vi.fn(async () => { throw error; });
      await expect(coordinator.run({ key: `read:${status}`, operation })).rejects.toBe(error);
      expect(operation).toHaveBeenCalledOnce();
    }
  });

  it("preserves a terminal HTTP error when its cleanup changes retry scope", async () => {
    const coordinator = new RetryCoordinator();
    const error = Object.assign(new Error("unauthorized"), { status: 401 });
    const pending = coordinator.run({
      key: "read:authorization-cleanup",
      operation: async () => {
        coordinator.setScope("anonymous");
        throw error;
      },
    });

    await expect(pending).rejects.toBe(error);
  });

  it("honors Retry-After for 429 and retryable gateway responses", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const operation = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error("busy"), { retryAfterMs: 5_000, status: 429 }))
      .mockResolvedValueOnce("ok");
    const pending = coordinator.run({ key: "read:busy", operation });
    await vi.advanceTimersByTimeAsync(4_999);
    expect(operation).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1);
    await expect(pending).resolves.toBe("ok");
  });

  it("does not replay a mutation without an idempotency contract", async () => {
    const coordinator = new RetryCoordinator();
    const error = transportError();
    const operation = vi.fn(async () => { throw error; });
    await expect(coordinator.run({ key: "mutation:create", method: "POST", operation })).rejects.toBe(error);
    expect(operation).toHaveBeenCalledOnce();
  });

  it("retries a mutation only with a stable key, fingerprint, and server deduplication", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const contract = approvedMutation();
    expect(idempotencyHeaders(contract)).toEqual({ "Idempotency-Key": contract.idempotencyKey });
    const operation = vi.fn().mockRejectedValueOnce(transportError()).mockResolvedValueOnce("created");
    const pending = coordinator.run({
      key: "mutation:create",
      ...TEST_MUTATION_TARGET,
      mutation: contract,
      operation,
    });
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(pending).resolves.toBe("created");
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it("derives a stable SHA-256 fingerprint from exact mutation semantics", async () => {
    const serialized = JSON.stringify({ action: "set", values: ["one", "two"] });
    const first = await createRequestFingerprint(serialized);
    const second = await createRequestFingerprint(serialized);

    expect(first).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(second).toBe(first);
    expect(await createRequestFingerprint(`${serialized} `)).not.toBe(first);
  });

  it("single-flights an idempotent mutation by server key, not caller label", async () => {
    let resolve!: (value: string) => void;
    const operation = vi.fn(() => new Promise<string>((done) => { resolve = done; }));
    const mutation = approvedMutation();
    const coordinator = new RetryCoordinator();

    const first = coordinator.run({ key: "button-a", ...TEST_MUTATION_TARGET, mutation, operation });
    const second = coordinator.run({ key: "button-b", ...TEST_MUTATION_TARGET, mutation, operation });
    expect(second).toBe(first);
    resolve("created");
    await expect(first).resolves.toBe("created");
    expect(operation).toHaveBeenCalledOnce();
  });

  it("rejects reuse of an idempotency key with a different request body", async () => {
    const coordinator = new RetryCoordinator();
    const idempotencyKey = createIdempotencyKey();
    await coordinator.run({
      key: "first",
      ...TEST_MUTATION_TARGET,
      mutation: approvedMutation(idempotencyKey, fingerprint("a")),
      operation: async () => "created",
    });

    expect(() => coordinator.run({
      key: "second",
      ...TEST_MUTATION_TARGET,
      mutation: approvedMutation(idempotencyKey, fingerprint("b")),
      operation: async () => "created-again",
    })).toThrow(/different request fingerprint/);
  });

  it("caps mutation attempts even with deduplication", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({
      maxMutationAttempts: 3,
      random: () => 0.5,
    });
    const error = transportError();
    const pending = coordinator.run({
      key: "mutation:update",
      ...TEST_MUTATION_TARGET,
      mutation: approvedMutation(),
      operation: async () => { throw error; },
    });
    void pending.catch(() => undefined);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(pending).rejects.toBe(error);
  });

  it("rejects mutation retry fingerprints that are not canonical SHA-256 digests", () => {
    for (const requestFingerprint of [
      "sha256:body",
      `sha256:${"g".repeat(64)}`,
      `sha512:${"a".repeat(64)}`,
      `sha256:${"a".repeat(63)}`,
    ]) {
      expect(() => approvedMutation(createIdempotencyKey(), requestFingerprint)).toThrow(/SHA-256/i);
    }
  });

  it("rejects mutation retry without a versioned registered audit identity", () => {
    expect(() => createMutationRetryContract({
      ...TEST_MUTATION_TARGET,
      auditId: "unregistered contract",
      idempotencyKey: createIdempotencyKey(),
      requestFingerprint: fingerprint(),
    })).toThrow(/audit id/i);
  });

  it("rejects a well-formed mutation audit id that is absent from the approved registry", () => {
    expect(() => createMutationRetryContract({
      ...TEST_MUTATION_TARGET,
      auditId: "unknown.retry-contract.v1",
      idempotencyKey: createIdempotencyKey(),
      requestFingerprint: fingerprint(),
    })).toThrow(/approved audit registry/i);
  });

  it("binds each approved audit identity to its exact method, endpoint, and action", () => {
    for (const target of [
      { ...TEST_MUTATION_TARGET, method: "PATCH" },
      { ...TEST_MUTATION_TARGET, endpoint: "/api/apps/storage/backend" },
      { ...TEST_MUTATION_TARGET, action: "pinned_apps.delete" },
    ]) {
      expect(() => createMutationRetryContract({
        ...target,
        auditId: TEST_RETRY_AUDIT_ID,
        idempotencyKey: createIdempotencyKey(),
        requestFingerprint: fingerprint(),
      })).toThrow(/approved mutation target/i);
    }

    const coordinator = new RetryCoordinator();
    const mutation = approvedMutation();
    expect(() => coordinator.run({
      key: "mutation:wrong-method",
      ...TEST_MUTATION_TARGET,
      method: "PATCH",
      mutation,
      operation: async () => "created",
    })).toThrow(/method/i);
    expect(() => coordinator.run({
      key: "mutation:wrong-endpoint",
      ...TEST_MUTATION_TARGET,
      endpoint: "/api/apps/storage/backend",
      mutation,
      operation: async () => "created",
    })).toThrow(/endpoint/i);
    expect(() => coordinator.run({
      key: "mutation:wrong-action",
      ...TEST_MUTATION_TARGET,
      action: "pinned_apps.delete",
      mutation,
      operation: async () => "created",
    })).toThrow(/action/i);
  });

  it("rejects a structurally forged retry contract that did not come from the factory", () => {
    const coordinator = new RetryCoordinator();
    const forged = {
      ...TEST_MUTATION_TARGET,
      auditId: TEST_RETRY_AUDIT_ID,
      idempotencyKey: createIdempotencyKey(),
      requestFingerprint: fingerprint(),
      serverDeduplicates: true,
    } as unknown as MutationRetryContract;

    expect(() => coordinator.run({
      key: "mutation:forged",
      ...TEST_MUTATION_TARGET,
      mutation: forged,
      operation: async () => "created",
    })).toThrow(/factory/i);
    expect(() => idempotencyHeaders(forged)).toThrow(/factory/i);
  });

  it("pauses scheduled retries while hidden and resumes on a visibility hint", async () => {
    vi.useFakeTimers();
    let visible = true;
    const coordinator = new RetryCoordinator({ isVisible: () => visible, random: () => 0.5 });
    const operation = vi.fn().mockRejectedValueOnce(transportError()).mockResolvedValueOnce("ok");
    const pending = coordinator.run({ key: "read:hidden", operation });
    visible = false;
    await vi.advanceTimersByTimeAsync(1_000);
    expect(operation).toHaveBeenCalledOnce();
    visible = true;
    coordinator.hint();
    await expect(pending).resolves.toBe("ok");
  });

  it("pauses retries while the Maverick app frame is hidden", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const operation = vi.fn().mockRejectedValueOnce(transportError()).mockResolvedValueOnce("ok");
    const pending = coordinator.run({ key: "read:hidden-frame", operation });
    coordinator.setClientVisibility(false);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(operation).toHaveBeenCalledOnce();

    coordinator.setClientVisibility(true);
    await expect(pending).resolves.toBe("ok");
  });

  it("cancels pending work on abort and scope change", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator();
    const controller = new AbortController();
    const aborted = coordinator.run({ key: "read:abort", operation: async () => { throw transportError(); }, signal: controller.signal });
    controller.abort();
    await expect(aborted).rejects.toBeInstanceOf(RetryCancelledError);

    const scoped = coordinator.run({ key: "read:scope", operation: async () => { throw transportError(); } });
    coordinator.setScope("user-b/default");
    await expect(scoped).rejects.toBeInstanceOf(RetryCancelledError);
    expect(coordinator.pendingCount()).toBe(0);
  });

  it("reports cancellation duration for an externally aborted wait", async () => {
    vi.useFakeTimers();
    const telemetry: Array<Record<string, unknown>> = [];
    const coordinator = new RetryCoordinator({ telemetry: (event) => telemetry.push(event) });
    const controller = new AbortController();
    const pending = coordinator.run({
      key: "read:cancelled-wait",
      operation: async () => { throw transportError(); },
      signal: controller.signal,
    });
    await vi.advanceTimersByTimeAsync(400);
    controller.abort();

    await expect(pending).rejects.toBeInstanceOf(RetryCancelledError);
    expect(telemetry.map((event) => event.kind)).toEqual(["wait_started", "cancelled"]);
    expect(telemetry.at(-1)).toMatchObject({ durationMs: 400 });
  });
});
