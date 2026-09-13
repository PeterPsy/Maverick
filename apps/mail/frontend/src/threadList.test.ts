import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MailThread } from './api';
import { readMailDisplay } from './pwaCache';
import { readMailThreadList, type ThreadListPayload } from './threadList';

vi.mock('./pwaCache', () => ({ readMailDisplay: vi.fn() }));

function page(offset: number, total: number): ThreadListPayload {
  return {
    offset, total_count: total, limit: 200,
    items: Array.from({ length: Math.min(200, Math.max(0, total - offset)) }, (_, index) => ({
      id: `thread-${offset + index}`, connection_id: 'a', labels: ['inbox'],
    } as MailThread)),
  };
}

describe('Mail header collection', () => {
  beforeEach(() => vi.resetAllMocks());

  it('reads every cached page without narrowing to a mailbox or UI page', async () => {
    vi.mocked(readMailDisplay).mockImplementation(async (params) => page(Number(params.offset), 451) as never);
    const update = vi.fn();
    await readMailThreadList('attachment-name.pdf', new AbortController().signal, update, vi.fn());
    expect(vi.mocked(readMailDisplay).mock.calls.map(([params]) => params)).toEqual([0, 200, 400].map((offset) => ({
      kind: 'threads', offset, max_threads: 200, query: 'attachment-name.pdf',
    })));
    expect(update.mock.calls.map(([items, complete]) => [items.length, complete]))
      .toEqual([[200, false], [400, false], [451, true]]);
  });

  it('follows revalidation growth and shrinkage instead of retaining stale pages', async () => {
    vi.mocked(readMailDisplay).mockImplementation(async (params) => page(Number(params.offset), 201) as never);
    const update = vi.fn();
    await readMailThreadList('', new AbortController().signal, update, vi.fn());
    const revalidate = vi.mocked(readMailDisplay).mock.calls[0][1]!.onRevalidated!;
    revalidate(page(0, 1));
    expect(update.mock.calls.at(-1)?.[0]).toHaveLength(1);
    revalidate(page(0, 201));
    await vi.waitFor(() => expect(update.mock.calls.at(-1)?.[0]).toHaveLength(201));
    expect(vi.mocked(readMailDisplay).mock.calls.filter(([params]) => params.offset === 200)).toHaveLength(2);
  });

  it('ignores stale revalidation after the search is aborted', async () => {
    vi.mocked(readMailDisplay).mockResolvedValue(page(0, 1) as never);
    const controller = new AbortController();
    const update = vi.fn();
    await readMailThreadList('', controller.signal, update, vi.fn());
    controller.abort();
    vi.mocked(readMailDisplay).mock.calls[0][1]!.onRevalidated!(page(0, 0));
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('deduplicates overlaps between page snapshots', async () => {
    vi.mocked(readMailDisplay).mockImplementation(async (params) => {
      const result = page(Number(params.offset), 201);
      if (params.offset === 200) result.items[0] = { ...result.items[0], id: 'thread-0', labels: ['trash'] };
      return result as never;
    });
    const update = vi.fn();
    await readMailThreadList('', new AbortController().signal, update, vi.fn());
    expect(update.mock.calls.at(-1)?.[0]).toHaveLength(200);
    expect(update.mock.calls.at(-1)?.[0][0].labels).toEqual(['inbox']);
    expect(update.mock.calls.at(-1)?.[1]).toBe(true);
  });

  it('reports a failed later page rather than declaring the partial list complete', async () => {
    vi.mocked(readMailDisplay).mockImplementation(async (params) => {
      if (params.offset === 200) throw new Error('Offline');
      return page(0, 201) as never;
    });
    const update = vi.fn();
    await expect(readMailThreadList('', new AbortController().signal, update, vi.fn())).rejects.toThrow('Offline');
    expect(update.mock.calls.at(-1)?.[1]).toBe(false);
  });
});
