import { afterEach, describe, expect, it, vi } from 'vitest';
import { PreviewMemoryCache } from './previewMemoryCache';
import { schedulePreviewConversion } from './previewConversions';

afterEach(() => vi.restoreAllMocks());

describe('preview resource ownership', () => {
  it('pins displayed URLs, evicts unpinned LRU values, and releases uncached values', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const cache = new PreviewMemoryCache(1300, 1000);
    const first = cache.remember('a', { text: '', url: 'blob:a', bytes: 300 });
    const second = cache.remember('b', { text: '', url: 'blob:b', bytes: 300 });
    second.release();
    const third = cache.remember('c', { text: '', url: 'blob:c', bytes: 300 });
    expect(revoke.mock.calls).toEqual([['blob:b']]);
    const tooLarge = cache.remember('large', { text: '', url: 'blob:large', bytes: 5000 });
    expect(cache.get('large')).toBeNull();
    tooLarge.release();
    tooLarge.release();
    expect(revoke.mock.calls).toEqual([['blob:b'], ['blob:large']]);
    first.release();
    third.release();
    cache.clear();
    expect(revoke.mock.calls).toEqual([['blob:b'], ['blob:large'], ['blob:a'], ['blob:c']]);
  });

  it('one consumer abort cannot revoke another consumer URL, and identity purge clears every lease', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const cache = new PreviewMemoryCache();
    const left = new AbortController();
    cache.remember('same', { text: '', url: 'blob:same' }, left.signal);
    const right = cache.get('same')!;
    left.abort();
    expect(revoke).not.toHaveBeenCalled();
    cache.clear();
    right.release();
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:same');
  });

  it('late cancelled resources are disposed without entering the cache', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const cache = new PreviewMemoryCache();
    const controller = new AbortController();
    controller.abort();
    expect(() => cache.remember('late', { text: '', url: 'blob:late' }, controller.signal)).toThrow();
    expect(cache.get('late')).toBeNull();
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:late');
  });
});

describe('conversion admission', () => {
  it('starts at most two tasks and removes cancelled queued work', async () => {
    let finishFirst!: () => void;
    let finishSecond!: () => void;
    const firstTask = vi.fn(() => new Promise<void>(resolve => { finishFirst = resolve; }));
    const secondTask = vi.fn(() => new Promise<void>(resolve => { finishSecond = resolve; }));
    const queuedTask = vi.fn(async () => undefined);
    const controller = new AbortController();
    const first = schedulePreviewConversion(firstTask);
    const second = schedulePreviewConversion(secondTask);
    const queued = schedulePreviewConversion(queuedTask, controller.signal);
    const rejected = expect(queued).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    expect(firstTask).toHaveBeenCalledOnce();
    expect(secondTask).toHaveBeenCalledOnce();
    expect(queuedTask).not.toHaveBeenCalled();
    controller.abort();
    await rejected;
    finishFirst();
    finishSecond();
    await Promise.all([first, second]);
    expect(queuedTask).not.toHaveBeenCalled();
  });
});
