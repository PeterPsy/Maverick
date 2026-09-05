/** Keep contiguous bounded pages coherent when conditional revalidation grows or
 * shrinks a result. Later pages never overwrite a newer revalidated page. */
export async function readAppCachePages<T>(options: {
  signal: AbortSignal;
  pageSize: number;
  readPage: (offset: number, onRevalidated: (page: T) => void) => Promise<T>;
  hasMore: (page: T) => boolean;
  onUpdate: (pages: T[]) => void;
  onError: (error: unknown) => void;
}): Promise<void> {
  if (!Number.isSafeInteger(options.pageSize) || options.pageSize <= 0) throw new TypeError("Invalid display page size.");
  const pages = new Map<number, T>();
  const inFlight = new Map<number, Promise<void>>();
  const publish = () => {
    if (options.signal.aborted) return;
    const contiguous: T[] = [];
    for (let offset = 0; pages.has(offset); offset += options.pageSize) {
      const page = pages.get(offset)!;
      contiguous.push(page);
      if (!options.hasMore(page)) break;
    }
    options.onUpdate(contiguous);
  };
  const reachable = (offset: number) => {
    for (let previous = 0; previous < offset; previous += options.pageSize) {
      if (!pages.has(previous) || !options.hasMore(pages.get(previous)!)) return false;
    }
    return true;
  };
  async function ensure(offset: number): Promise<void> {
    if (options.signal.aborted) return;
    if (inFlight.has(offset)) return inFlight.get(offset);
    if (pages.has(offset)) return;
    let revalidated = false;
    const accept = (page: T) => {
      if (options.signal.aborted || !reachable(offset)) return;
      pages.set(offset, page);
      if (!options.hasMore(page)) for (const key of pages.keys()) if (key > offset) pages.delete(key);
      publish();
    };
    const pending = options.readPage(offset, (page) => {
      revalidated = true;
      accept(page);
      if (options.hasMore(page)) void ensure(offset + options.pageSize).catch(options.onError);
    }).then(async (page) => {
      if (options.signal.aborted) return;
      if (!revalidated) accept(page);
      if (reachable(offset) && pages.has(offset) && options.hasMore(pages.get(offset)!)) await ensure(offset + options.pageSize);
    }).finally(() => inFlight.delete(offset));
    inFlight.set(offset, pending);
    return pending;
  }
  await ensure(0);
}
