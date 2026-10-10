import { afterEach, describe, expect, it, vi } from 'vitest';
import { callBackend } from './api';

describe('Mail request cancellation', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  function pendingFetch() {
    const fetch = vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      const signal = options.signal!;
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
      if (signal.aborted) reject(signal.reason);
    }));
    vi.stubGlobal('fetch', fetch);
    return fetch;
  }
  it('aborts the direct request when its caller cancels', async () => {
    const fetch = pendingFetch();
    const controller = new AbortController();
    const request = callBackend({ action: 'drafts.list' }, { signal: controller.signal });
    const assertion = expect(request).rejects.toThrow('Cancelled');
    controller.abort(new Error('Cancelled'));
    await assertion;
    expect(fetch.mock.calls[0][1].signal?.aborted).toBe(true);
  });
  it('aborts the direct request at the configured timeout', async () => {
    vi.useFakeTimers();
    pendingFetch();
    const request = callBackend({ action: 'drafts.list' }, { timeoutMs: 100 });
    const assertion = expect(request).rejects.toThrow('Mail request timed out');
    await vi.advanceTimersByTimeAsync(100);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
  });
});
