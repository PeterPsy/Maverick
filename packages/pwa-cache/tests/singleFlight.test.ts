import { describe, expect, it, vi } from "vitest";
import { runSingleFlight } from "../src/singleFlight";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("single-flight consumer cancellation", () => {
  it.each([0, 1])("cancels only consumer %s while sharing the request", async (cancelled) => {
    const response = deferred<string>();
    const controllers = [new AbortController(), new AbortController()];
    let requestSignal!: AbortSignal;
    const operation = vi.fn(async (signal: AbortSignal) => { requestSignal = signal; return response.promise; });
    const reads = controllers.map((controller) => runSingleFlight("shared", operation, controller.signal));
    await vi.waitFor(() => expect(operation).toHaveBeenCalledOnce());
    const rejected = expect(reads[cancelled]).rejects.toMatchObject({ name: "AbortError" });
    controllers[cancelled].abort();
    await rejected;
    expect(requestSignal.aborted).toBe(false);
    response.resolve("fresh");
    await expect(reads[1 - cancelled]).resolves.toBe("fresh");
  });

  it("aborts abandoned work and lets a new reader start even if the old loader ignores abort", async () => {
    const response = deferred<string>();
    const controller = new AbortController();
    let requestSignal!: AbortSignal;
    const operation = vi.fn(async (signal: AbortSignal) => { requestSignal = signal; return response.promise; });
    const read = runSingleFlight("abandoned", operation, controller.signal);
    await vi.waitFor(() => expect(operation).toHaveBeenCalledOnce());
    const rejected = expect(read).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await rejected;
    expect(requestSignal.aborted).toBe(true);
    await expect(runSingleFlight("abandoned", async () => "new")).resolves.toBe("new");
    response.resolve("late");
  });

  it("does not admit a pre-cancelled consumer or run its loader", async () => {
    const operation = vi.fn(async () => "unexpected");
    await expect(runSingleFlight("cancelled", operation, AbortSignal.abort())).rejects.toMatchObject({ name: "AbortError" });
    expect(operation).not.toHaveBeenCalled();
  });
});
