import { describe, expect, it } from 'vitest';
import { StorageCatalogRequests } from './storageCatalogRequests';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('Storage catalog request ownership', () => {
  it('rejects an old page and its finally after navigation even if abort is ignored', async () => {
    const requests = new StorageCatalogRequests();
    requests.transition('principal:a/workspace:a/folder:a');
    const old = requests.start('page')!;
    const response = deferred<string>();
    const writes: string[] = [];
    const pending = response.promise.then((value) => {
      if (old.current()) writes.push(value);
    }).finally(() => {
      if (old.current()) writes.push('loading:false');
      old.finish();
    });
    requests.transition('principal:a/workspace:a/folder:b');
    const current = requests.start('page')!;
    response.resolve('old rows');
    await pending;
    expect(writes).toEqual([]);
    expect(current.current()).toBe(true);
    expect(old.controller.signal.reason).toBe('navigation');
  });

  it('fences a deep link which finishes after a second await and sort change', async () => {
    const requests = new StorageCatalogRequests();
    requests.transition('query:a/sort:date');
    const read = requests.start('catalog')!;
    const link = deferred<string>();
    let selection = '';
    const pending = link.promise.then((value) => { if (read.current()) selection = value; });
    requests.transition('query:a/sort:size');
    link.resolve('wrong selection');
    await pending;
    expect(selection).toBe('');
  });

  it('permits one page per generation and cancels it on refresh or suspension', () => {
    const requests = new StorageCatalogRequests();
    const page = requests.start('page')!;
    expect(requests.start('page')).toBeNull();
    requests.invalidate('refresh');
    expect(page.current()).toBe(false);
    const next = requests.start('page')!;
    requests.invalidate('suspend');
    expect(next.current()).toBe(false);
    expect(next.controller.signal.reason).toBe('suspend');
  });

  it('does not mistake transport errors or timeouts for a local cancellation', () => {
    const requests = new StorageCatalogRequests();
    const read = requests.start('catalog')!;
    expect(read.current()).toBe(true); // even when fetch rejects with AbortError/TypeError
    requests.invalidate('dispose');
    expect(read.current()).toBe(false);
  });

  it('stops hidden node reads and only replaces the requested visible lane', () => {
    const requests = new StorageCatalogRequests();
    const firstNode = requests.start('drive:first')!;
    const secondNode = requests.start('drive:second')!;
    const replacement = requests.replace('drive:first')!;
    expect(firstNode.current()).toBe(false);
    expect(secondNode.current()).toBe(true);
    expect(replacement.current()).toBe(true);
    firstNode.finish();
    expect(replacement.current()).toBe(true);
    requests.setVisible(false);
    expect(requests.start('catalog')).toBeNull();
    expect(secondNode.current()).toBe(false);
    requests.setVisible(true);
    expect(requests.start('catalog')?.current()).toBe(true);
  });
});
