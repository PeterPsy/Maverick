import { expect, it, vi } from 'vitest';
import { readAppCachePages } from '../src/appReadModelPages';
it('fetches newly added pages after warm revalidation and hides removed tails', async () => {
  const callbacks = new Map<number, (page: { more: boolean; label: string }) => void>();
  const update = vi.fn();
  await readAppCachePages<{ more: boolean; label: string }>({
    signal: new AbortController().signal, pageSize: 10, hasMore: (page) => page.more,
    onUpdate: update, onError: (error) => { throw error; },
    readPage: async (offset, callback) => { callbacks.set(offset, callback); return { more:false,label:String(offset) }; },
  });
  expect(update).toHaveBeenLastCalledWith([{more:false,label:'0'}]);
  callbacks.get(0)!({more:true,label:'changed'});
  await vi.waitFor(() => expect(update).toHaveBeenLastCalledWith([{more:true,label:'changed'},{more:false,label:'10'}]));
  callbacks.get(0)!({more:false,label:'shrunk'});
  expect(update).toHaveBeenLastCalledWith([{more:false,label:'shrunk'}]);
});
