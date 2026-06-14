import type { ChatThread, RuntimeEvent } from "../../api/client";
import { threadSearchCacheKey, transcriptSearchTextFromEvents, type TranscriptSearchTextByThreadId } from "./search";

export type TranscriptSearchCacheEntry = {
  cacheKey: string;
  text: string;
};

export type TranscriptSearchCache = Map<string, TranscriptSearchCacheEntry>;

export function isAbortError(error: unknown): boolean {
  return typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "AbortError";
}

export function transcriptSearchSnapshot(threads: ChatThread[], cache: TranscriptSearchCache): TranscriptSearchTextByThreadId {
  const snapshot: TranscriptSearchTextByThreadId = {};
  for (const thread of threads) {
    const cached = cache.get(thread.thread_id);
    if (cached && cached.cacheKey === threadSearchCacheKey(thread)) {
      snapshot[thread.thread_id] = cached.text;
    }
  }
  return snapshot;
}

export function threadsNeedingTranscriptIndex(threads: ChatThread[], cache: TranscriptSearchCache): ChatThread[] {
  return threads.filter((thread) => {
    if (!thread.runtime_session_id) {
      return false;
    }
    const cached = cache.get(thread.thread_id);
    return !cached || cached.cacheKey !== threadSearchCacheKey(thread);
  });
}

export async function indexTranscriptSearchText({
  allThreads,
  cache,
  eventLimit,
  loadEvents,
  maxConcurrent,
  onProgress,
  signal,
  threadsToIndex,
}: {
  allThreads: ChatThread[];
  cache: TranscriptSearchCache;
  eventLimit: number;
  loadEvents: (sessionId: string, options: { limit: number; signal: AbortSignal }) => Promise<{ items: RuntimeEvent[] }>;
  maxConcurrent: number;
  onProgress?: (snapshot: TranscriptSearchTextByThreadId) => void;
  signal: AbortSignal;
  threadsToIndex: ChatThread[];
}): Promise<TranscriptSearchTextByThreadId> {
  const workerCount = Math.min(Math.max(1, Math.floor(maxConcurrent)), threadsToIndex.length);
  let nextThreadIndex = 0;

  async function indexNextThread(): Promise<void> {
    while (!signal.aborted) {
      const thread = threadsToIndex[nextThreadIndex];
      nextThreadIndex += 1;
      if (!thread) {
        return;
      }
      const cacheKey = threadSearchCacheKey(thread);
      try {
        const payload = await loadEvents(thread.runtime_session_id, { limit: eventLimit, signal });
        if (signal.aborted) {
          return;
        }
        cache.set(thread.thread_id, {
          cacheKey,
          text: transcriptSearchTextFromEvents(payload.items || []),
        });
        onProgress?.(transcriptSearchSnapshot(allThreads, cache));
      } catch (loadError) {
        if (isAbortError(loadError) || signal.aborted) {
          return;
        }
        cache.set(thread.thread_id, { cacheKey, text: "" });
        onProgress?.(transcriptSearchSnapshot(allThreads, cache));
      }
    }
  }

  if (!workerCount) {
    return transcriptSearchSnapshot(allThreads, cache);
  }
  await Promise.all(Array.from({ length: workerCount }, () => indexNextThread()));
  return transcriptSearchSnapshot(allThreads, cache);
}
