import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { observeBootstrapConfirmation } from './bootstrapConfirmation';
import type { SidecarLaunch } from './types';

const mocks = vi.hoisted(() => ({ read: vi.fn(), visible: true, notify: (_visible: boolean) => {}, stop: vi.fn() }));
vi.mock('@maverick/pwa-cache', () => ({ observeMaverickVisibility: (notify: (visible: boolean) => void) => {
  mocks.notify = notify;
  notify(mocks.visible);
  return mocks.stop;
} }));
vi.mock('./api', async importOriginal => ({ ...await importOriginal<typeof import('./api')>(),
  requestOpenDesignBootstrapStatus: mocks.read }));

const launch = { expires_in_seconds: 30 } as SidecarLaunch;
describe('native bootstrap confirmation lifecycle', () => {
  let controller: AbortController;
  let ready: ReturnType<typeof vi.fn<() => void>>;
  let error: ReturnType<typeof vi.fn<(error: unknown) => void>>;
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.read.mockReset().mockResolvedValue('pending');
    mocks.stop.mockReset();
    mocks.visible = true;
    controller = new AbortController();
    ready = vi.fn(); error = vi.fn();
  });
  afterEach(() => { controller.abort(); vi.useRealTimers(); });
  const start = () => observeBootstrapConfirmation('design-studio', launch, controller.signal, ready, error);

  it('removes pending timers while hidden and performs one confirmation on resume', async () => {
    start();
    await vi.advanceTimersByTimeAsync(200);
    expect(mocks.read).toHaveBeenCalledTimes(2);
    mocks.notify(false);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mocks.read).toHaveBeenCalledTimes(2);
    mocks.read.mockResolvedValue('ready');
    mocks.notify(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.read).toHaveBeenCalledTimes(3);
    expect(ready).toHaveBeenCalledOnce();
    expect(mocks.stop).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mocks.read).toHaveBeenCalledTimes(3);
  });

  it('aborts an in-flight read and ignores a late result after hide/resume', async () => {
    let resolve!: (status: string) => void;
    mocks.read.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    start();
    const signal = mocks.read.mock.calls[0][2] as AbortSignal;
    mocks.notify(false);
    expect(signal.aborted).toBe(true);
    mocks.notify(true);
    resolve('ready');
    await vi.advanceTimersByTimeAsync(0);
    expect(ready).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });

  it('does not read initially offline and checks an expired confirmation once on resume', async () => {
    mocks.visible = false;
    start();
    await vi.advanceTimersByTimeAsync(31_000);
    expect(mocks.read).not.toHaveBeenCalled();
    mocks.notify(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.read).toHaveBeenCalledOnce();
    expect(error).toHaveBeenCalledWith(expect.objectContaining({ code: 'sidecar_bootstrap_unconfirmed' }));
    expect(mocks.stop).toHaveBeenCalledOnce();
  });

  it('unsubscribes and aborts when a launch is replaced, without reporting cancellation', async () => {
    mocks.read.mockImplementation((_app, _launch, signal: AbortSignal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    start();
    controller.abort();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(mocks.stop).toHaveBeenCalledOnce();
    expect(error).not.toHaveBeenCalled();
    expect(ready).not.toHaveBeenCalled();
    expect(mocks.read).toHaveBeenCalledOnce();
  });
});
