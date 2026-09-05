import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MutationRetryTransportError,
  RetryCancelledError,
  RetryCoordinator,
  createIdempotencyKey,
  createMutationRetryExecutor,
  createRequestFingerprint,
  createSafeRequestRetryExecutor,
  type MutationRetryExecutor,
  type SafeRequestRetryExecutor,
} from "../src";

const TEST_RETRY_AUDIT_ID = "base-shell.pinned-apps.set.v1";
const TEST_SAFE_ENDPOINT = "/api/test/read";
const TEST_MUTATION_TARGET = {
  action: "pinned_apps.set",
  endpoint: "/api/apps/app-store/backend",
  method: "POST",
} as const;

function approvedMutation(
  idempotencyKey = createIdempotencyKey(),
  request: Readonly<Record<string, unknown>> = {
    action: TEST_MUTATION_TARGET.action,
    app_ids: ["chat"],
  },
): Promise<MutationRetryExecutor> {
  return createMutationRetryExecutor({
    auditId: TEST_RETRY_AUDIT_ID,
    ...TEST_MUTATION_TARGET,
    idempotencyKey,
    request,
  });
}

function safeRequest(endpoint = TEST_SAFE_ENDPOINT) {
  return createSafeRequestRetryExecutor({ endpoint, method: "GET" });
}

function jsonResponse(value: unknown, status = 200, headers: HeadersInit = {}): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("RAM retry coordinator", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("retries idempotent reads with capped exponential delay and single flight", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("link down"))
      .mockRejectedValueOnce(new TypeError("link flapped"))
      .mockResolvedValueOnce(jsonResponse("ok"));
    const executor = safeRequest();
    const first = coordinator.runRequest<string>({ executor, key: "shell:session" });
    const second = coordinator.runRequest<string>({ executor, key: "shell:session" });
    expect(first).toBe(second);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(first).resolves.toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not coalesce different concrete endpoints that reuse a caller key", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse("first"))
      .mockResolvedValueOnce(jsonResponse("second"));
    const coordinator = new RetryCoordinator();

    const first = coordinator.runRequest<string>({
      executor: safeRequest("/api/test/first"),
      key: "read:shared-label",
    });
    const second = coordinator.runRequest<string>({
      executor: safeRequest("/api/test/second"),
      key: "read:shared-label",
    });

    await expect(Promise.all([first, second])).resolves.toEqual(["first", "second"]);
    expect(fetchMock.mock.calls.map(([target]) => target)).toEqual([
      "/api/test/first",
      "/api/test/second",
    ]);
  });

  it("reports one bounded wait lifecycle across retries", async () => {
    vi.useFakeTimers();
    const telemetry: Array<Record<string, unknown>> = [];
    const coordinator = new RetryCoordinator({
      random: () => 0.5,
      telemetry: (event) => telemetry.push(event),
    });
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("link down"))
      .mockRejectedValueOnce(new TypeError("link flapped"))
      .mockResolvedValueOnce(jsonResponse("ok"));
    const pending = coordinator.runRequest<string>({
      executor: safeRequest(),
      key: "read:observed",
    });

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
    const fetchMock = vi.spyOn(globalThis, "fetch");
    for (const status of [401, 403, 409, 422]) {
      const coordinator = new RetryCoordinator();
      fetchMock.mockResolvedValueOnce(new Response(null, { status }));
      await expect(coordinator.runRequest({
        executor: safeRequest(),
        key: `read:${status}`,
      })).rejects.toMatchObject({ status });
    }
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("preserves a terminal HTTP error when its cleanup changes retry scope", async () => {
    const coordinator = new RetryCoordinator();
    const error = Object.assign(new Error("unauthorized"), { status: 401 });
    const pending = coordinator.runOpaque({
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
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 429, headers: { "Retry-After": "5" } }))
      .mockResolvedValueOnce(jsonResponse("ok"));
    const pending = coordinator.runRequest<string>({ executor: safeRequest(), key: "read:busy" });
    await vi.advanceTimersByTimeAsync(4_999);
    expect(fetchMock).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1);
    await expect(pending).resolves.toBe("ok");
  });

  it("never replays an opaque callback even if it issues an unsafe request", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValue(new TypeError("transport interrupted after send"));
    const pending = coordinator.runOpaque({
      key: "mutation:unsafe",
      operation: () => globalThis.fetch("/api/unsafe/non-deduplicated", { method: "DELETE" }),
    });

    await expect(pending).rejects.toBeInstanceOf(TypeError);
    await vi.runAllTimersAsync();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("does not expose the internal callback coordinator as a JavaScript method", () => {
    const coordinator = new RetryCoordinator() as unknown as Record<string, unknown>;

    expect(coordinator.coordinate).toBeUndefined();
    expect(coordinator.execute).toBeUndefined();
  });

  it("admits only a factory-issued safe HTTP executor to the read retry path", () => {
    const coordinator = new RetryCoordinator();
    expect(() => createSafeRequestRetryExecutor({
      endpoint: "/api/unsafe/non-deduplicated",
      method: "DELETE",
    })).toThrow(/only GET, HEAD, or OPTIONS/i);

    const executor = safeRequest();
    expect(() => coordinator.runRequest({
      executor,
      key: "read:opaque-bypass",
      operation: () => globalThis.fetch("/api/unsafe/non-deduplicated", { method: "DELETE" }),
    } as never)).toThrow(/SDK-owned safe request executor/i);

    const forged = {
      endpoint: TEST_SAFE_ENDPOINT,
      method: "GET",
    } as unknown as SafeRequestRetryExecutor;
    expect(() => coordinator.runRequest({ executor: forged, key: "read:forged" }))
      .toThrow(/factory-issued/i);
  });

  it("retries only the exact SDK-owned HTTP request for an approved mutation", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("transport interrupted after send"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: "created" }), {
        headers: { "Content-Type": "application/json" },
      }));
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const executor = await approvedMutation();
    const pending = coordinator.runMutation<{ state: string }>({
      executor,
      key: "mutation:create",
    });

    await vi.advanceTimersByTimeAsync(1_000);
    await expect(pending).resolves.toEqual({ state: "created" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [target, init] of fetchMock.mock.calls) {
      expect(target).toBe(TEST_MUTATION_TARGET.endpoint);
      expect(init).toMatchObject({
        credentials: "same-origin",
        method: TEST_MUTATION_TARGET.method,
        redirect: "error",
        signal: expect.any(AbortSignal),
      });
      const headers = init?.headers as Record<string, string>;
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      expect(headers).toMatchObject({
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": executor.idempotencyKey,
      });
      expect(body).toEqual({
        action: TEST_MUTATION_TARGET.action,
        app_ids: ["chat"],
        idempotency_key: executor.idempotencyKey,
        request_fingerprint: executor.requestFingerprint,
      });
    }
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(fetchMock.mock.calls[1]?.[1]?.body);
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
    let resolve!: (value: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementation(() => new Promise<Response>((done) => { resolve = done; }));
    const executor = await approvedMutation();
    const coordinator = new RetryCoordinator();

    const first = coordinator.runMutation<string>({ executor, key: "button-a" });
    const second = coordinator.runMutation<string>({ executor, key: "button-b" });
    expect(second).toBe(first);
    resolve(new Response(JSON.stringify("created"), {
      headers: { "Content-Type": "application/json" },
    }));
    await expect(first).resolves.toBe("created");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects reuse of an idempotency key with a different request body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify("created"), {
      headers: { "Content-Type": "application/json" },
    }));
    const coordinator = new RetryCoordinator();
    const idempotencyKey = createIdempotencyKey();
    const first = await approvedMutation(idempotencyKey, {
      action: TEST_MUTATION_TARGET.action,
      app_ids: ["chat"],
    });
    const second = await approvedMutation(idempotencyKey, {
      action: TEST_MUTATION_TARGET.action,
      app_ids: ["storage"],
    });
    await coordinator.runMutation({ executor: first, key: "first" });

    expect(() => coordinator.runMutation({ executor: second, key: "second" }))
      .toThrow(/different request fingerprint/);
  });

  it("caps mutation attempts even with deduplication", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValue(new TypeError("transport interrupted after send"));
    const coordinator = new RetryCoordinator({
      maxMutationAttempts: 3,
      random: () => 0.5,
    });
    const pending = coordinator.runMutation({
      executor: await approvedMutation(),
      key: "mutation:update",
    });
    void pending.catch(() => undefined);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(pending).rejects.toBeInstanceOf(MutationRetryTransportError);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("snapshots exact JSON semantics and keeps deduplication fields SDK-owned", async () => {
    const request = { action: TEST_MUTATION_TARGET.action, app_ids: ["chat"] };
    const executor = await approvedMutation(createIdempotencyKey(), request);
    request.app_ids.push("storage");

    expect(executor.requestFingerprint).toMatch(/^sha256:[0-9a-f]{64}$/);
    await expect(approvedMutation(createIdempotencyKey(), {
      ...request,
      idempotency_key: "caller-owned",
    })).rejects.toThrow(/SDK-owned/i);
    await expect(approvedMutation(createIdempotencyKey(), {
      action: "pinned_apps.delete",
    })).rejects.toThrow(/JSON action/i);
    await expect(approvedMutation(createIdempotencyKey(), {
      action: TEST_MUTATION_TARGET.action,
      created_at: new Date(),
    })).rejects.toThrow(/exact JSON object/i);
    await expect(approvedMutation(createIdempotencyKey(), Object.defineProperty({}, "action", {
      enumerable: true,
      get: () => TEST_MUTATION_TARGET.action,
    }))).rejects.toThrow(/exact JSON object/i);
  });

  it("rejects mutation retry without a versioned registered audit identity", async () => {
    await expect(createMutationRetryExecutor({
      ...TEST_MUTATION_TARGET,
      auditId: "unregistered contract",
      idempotencyKey: createIdempotencyKey(),
      request: { action: TEST_MUTATION_TARGET.action },
    })).rejects.toThrow(/audit id/i);
  });

  it("rejects a well-formed mutation audit id that is absent from the approved registry", async () => {
    await expect(createMutationRetryExecutor({
      ...TEST_MUTATION_TARGET,
      auditId: "unknown.retry-contract.v1",
      idempotencyKey: createIdempotencyKey(),
      request: { action: TEST_MUTATION_TARGET.action },
    })).rejects.toThrow(/approved audit registry/i);
  });

  it("binds each approved audit identity to its exact method, endpoint, and action", async () => {
    for (const target of [
      { ...TEST_MUTATION_TARGET, method: "PATCH" },
      { ...TEST_MUTATION_TARGET, endpoint: "/api/apps/storage/backend" },
      { ...TEST_MUTATION_TARGET, action: "pinned_apps.delete" },
    ]) {
      await expect(createMutationRetryExecutor({
        ...target,
        auditId: TEST_RETRY_AUDIT_ID,
        idempotencyKey: createIdempotencyKey(),
        request: { action: target.action },
      })).rejects.toThrow(/approved mutation target/i);
    }
  });

  it("rejects every opaque callback on the mutation retry path", async () => {
    const coordinator = new RetryCoordinator();
    const executor = await approvedMutation();
    const unsafeOperation = vi.fn(async () => globalThis.fetch("/api/unsafe/non-deduplicated", {
      method: "DELETE",
    }));
    const computedBypass = {
      executor,
      key: "mutation:opaque-bypass",
      ...{ operation: unsafeOperation },
    };

    expect(() => coordinator.runMutation(computedBypass as never))
      .toThrow(/SDK-owned mutation executor/i);
    expect(() => coordinator.runOpaque({
      key: "mutation:legacy-bypass",
      method: "POST",
      mutation: executor,
      operation: unsafeOperation,
    } as never)).toThrow(/one-shot/i);
    expect(unsafeOperation).not.toHaveBeenCalled();
  });

  it("rejects a structurally forged retry executor that did not come from the factory", () => {
    const coordinator = new RetryCoordinator();
    const forged = {
      ...TEST_MUTATION_TARGET,
      auditId: TEST_RETRY_AUDIT_ID,
      idempotencyKey: createIdempotencyKey(),
      requestFingerprint: `sha256:${"a".repeat(64)}`,
      serverDeduplicates: true,
    } as unknown as MutationRetryExecutor;

    expect(() => coordinator.runMutation({
      executor: forged,
      key: "mutation:forged",
    })).toThrow(/factory/i);
  });

  it("pauses scheduled retries while hidden and resumes on a visibility hint", async () => {
    vi.useFakeTimers();
    let visible = true;
    const coordinator = new RetryCoordinator({ isVisible: () => visible, random: () => 0.5 });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("link down"))
      .mockResolvedValueOnce(jsonResponse("ok"));
    const pending = coordinator.runRequest<string>({ executor: safeRequest(), key: "read:hidden" });
    visible = false;
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledOnce();
    visible = true;
    coordinator.hint();
    await expect(pending).resolves.toBe("ok");
  });

  it("pauses retries while the Maverick app frame is hidden", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("link down"))
      .mockResolvedValueOnce(jsonResponse("ok"));
    const pending = coordinator.runRequest<string>({ executor: safeRequest(), key: "read:hidden-frame" });
    coordinator.setClientVisibility(false);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledOnce();

    coordinator.setClientVisibility(true);
    await expect(pending).resolves.toBe("ok");
  });

  it("cancels pending work on abort and scope change", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator();
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      })
    ));
    const controller = new AbortController();
    const aborted = coordinator.runRequest({ executor: safeRequest(), key: "read:abort", signal: controller.signal });
    controller.abort();
    await expect(aborted).rejects.toBeInstanceOf(RetryCancelledError);

    const scoped = coordinator.runRequest({ executor: safeRequest(), key: "read:scope" });
    coordinator.setScope("user-b/default");
    await expect(scoped).rejects.toBeInstanceOf(RetryCancelledError);
    expect(coordinator.pendingCount()).toBe(0);
  });

  it("reports cancellation duration for an externally aborted wait", async () => {
    vi.useFakeTimers();
    const telemetry: Array<Record<string, unknown>> = [];
    const coordinator = new RetryCoordinator({ telemetry: (event) => telemetry.push(event) });
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("link down"));
    const controller = new AbortController();
    const pending = coordinator.runRequest({
      executor: safeRequest(),
      key: "read:cancelled-wait",
      signal: controller.signal,
    });
    await vi.advanceTimersByTimeAsync(400);
    controller.abort();

    await expect(pending).rejects.toBeInstanceOf(RetryCancelledError);
    expect(telemetry.map((event) => event.kind)).toEqual(["wait_started", "cancelled"]);
    expect(telemetry.at(-1)).toMatchObject({ durationMs: 400 });
  });
});
