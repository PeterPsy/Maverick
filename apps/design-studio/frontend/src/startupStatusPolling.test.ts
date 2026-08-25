import { afterEach, describe, expect, it, vi } from "vitest";

import { startNonOverlappingPoll } from "./startupStatusPolling";

describe("startup status polling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits for the active request before scheduling another poll", async () => {
    vi.useFakeTimers();
    let resolvePoll: ((value: string) => void) | undefined;
    const poll = vi.fn(() => new Promise<string>((resolve) => {
      resolvePoll = resolve;
    }));
    const onResult = vi.fn();

    const stop = startNonOverlappingPoll({ intervalMs: 400, onResult, poll });
    expect(poll).toHaveBeenCalledOnce();

    await vi.advanceTimersByTimeAsync(4_000);
    expect(poll).toHaveBeenCalledOnce();

    resolvePoll?.("ready");
    await Promise.resolve();
    expect(onResult).toHaveBeenCalledWith("ready");

    await vi.advanceTimersByTimeAsync(399);
    expect(poll).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1);
    expect(poll).toHaveBeenCalledTimes(2);

    stop();
  });
});
