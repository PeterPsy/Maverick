import { readAppCachePages } from '@maverick/pwa-cache';
import type { MailThread } from './api';
import { readMailDisplay } from './pwaCache';

export type ThreadListPayload = {
  items: MailThread[];
  limit: number;
  offset: number;
  total_count: number;
};

const READ_PAGE_SIZE = 200;
const MAX_READ_OFFSET = 100_000;

function hasMore(page: ThreadListPayload) {
  return page.items.length > 0 && page.offset + page.items.length < page.total_count;
}

/** Load cached headers across folders once per search, not once per checkbox.
 * Search stays server-side so message bodies and attachment names still match. */
export async function readMailThreadList(
  query: string,
  signal: AbortSignal,
  onUpdate: (threads: MailThread[], complete: boolean) => void,
  onError: (error: unknown) => void,
) {
  await readAppCachePages<ThreadListPayload>({
    signal,
    pageSize: READ_PAGE_SIZE,
    hasMore,
    onError,
    onUpdate: (pages) => {
      const threads = new Map<string, MailThread>();
      for (const page of pages) for (const thread of page.items) {
        // A stale later page must not overwrite a thread that moved forward
        // into an earlier, freshly revalidated page.
        if (!threads.has(thread.id)) threads.set(thread.id, thread);
      }
      onUpdate([...threads.values()], !pages.length || !hasMore(pages[pages.length - 1]));
    },
    readPage: (offset, onRevalidated) => {
      // The store caps offsets; never loop over its last page or silently claim
      // that a partial collection is complete.
      if (offset > MAX_READ_OFFSET) throw new Error('Too many cached threads. Narrow the Mail search.');
      return readMailDisplay<ThreadListPayload>({
        kind: 'threads', max_threads: READ_PAGE_SIZE, offset,
        ...(query ? { query } : {}),
      }, { signal, onRevalidated, onRevalidationError: onError });
    },
  });
}
