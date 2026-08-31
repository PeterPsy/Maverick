import { afterEach, describe, expect, it, vi } from "vitest";
import {
  RetryCancelledError,
  RetryCoordinator,
  createIdempotencyKey,
  idempotencyHeaders,
} from "../src";

function transportError(): Error {
  return Object.assign(new Error("transport"), { name: "MaverickTransportError" });
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

  it("treats 401, 403, 409, and 422 as terminal", async () => {
    for (const status of [401, 403, 409, 422]) {
      const coordinator = new RetryCoordinator();
      const error = Object.assign(new Error(String(status)), { status });
      const operation = vi.fn(async () => { throw error; });
      await expect(coordinator.run({ key: `read:${status}`, operation })).rejects.toBe(error);
      expect(operation).toHaveBeenCalledOnce();
    }
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
    const contract = {
      idempotencyKey: createIdempotencyKey(),
      requestFingerprint: "sha256:body",
      serverDeduplicates: true as const,
    };
    expect(idempotencyHeaders(contract)).toEqual({ "Idempotency-Key": contract.idempotencyKey });
    const operation = vi.fn().mockRejectedValueOnce(transportError()).mockResolvedValueOnce("created");
    const pending = coordinator.run({ key: "mutation:create", method: "POST", mutation: contract, operation });
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(pending).resolves.toBe("created");
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it("single-flights an idempotent mutation by server key, not caller label", async () => {
    let resolve!: (value: string) => void;
    const operation = vi.fn(() => new Promise<string>((done) => { resolve = done; }));
    const mutation = {
      idempotencyKey: createIdempotencyKey(),
      requestFingerprint: "sha256:same-body",
      serverDeduplicates: true as const,
    };
    const coordinator = new RetryCoordinator();

    const first = coordinator.run({ key: "button-a", method: "POST", mutation, operation });
    const second = coordinator.run({ key: "button-b", method: "POST", mutation, operation });
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
      method: "POST",
      mutation: { idempotencyKey, requestFingerprint: "sha256:first", serverDeduplicates: true },
      operation: async () => "created",
    });

    expect(() => coordinator.run({
      key: "second",
      method: "POST",
      mutation: { idempotencyKey, requestFingerprint: "sha256:second", serverDeduplicates: true },
      operation: async () => "created-again",
    })).toThrow(/different request fingerprint/);
  });

  it("caps mutation attempts even with deduplication", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ maxMutationAttempts: 3, random: () => 0.5 });
    const error = transportError();
    const pending = coordinator.run({
      key: "mutation:update",
      method: "PATCH",
      mutation: {
        idempotencyKey: createIdempotencyKey(),
        requestFingerprint: "sha256:update",
        serverDeduplicates: true,
      },
      operation: async () => { throw error; },
    });
    void pending.catch(() => undefined);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(pending).rejects.toBe(error);
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
});
