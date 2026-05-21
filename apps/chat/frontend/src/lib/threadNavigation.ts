import { ChatThread, orderChatThreads } from "../api/client";

const THREAD_SYNC_DEBUG_STORAGE_KEY = "maverick.chat.debug.thread-sync";

export function findThreadByRuntimeSession(threads: ChatThread[], runtimeSessionId: string): ChatThread | null {
  return threads.find((thread) => thread.runtime_session_id === runtimeSessionId) || null;
}

export function upsertOrderedThread(threads: ChatThread[], thread: ChatThread): ChatThread[] {
  const nextThreads = threads.some((item) => item.thread_id === thread.thread_id)
    ? threads.map((item) => (item.thread_id === thread.thread_id ? { ...item, ...thread } : item))
    : [thread, ...threads];
  return orderChatThreads(nextThreads);
}

export function debugThreadSync(label: string, detail: Record<string, unknown> = {}) {
  try {
    if (window.localStorage.getItem(THREAD_SYNC_DEBUG_STORAGE_KEY) !== "1") {
      return;
    }
    console.debug(`[chat thread-sync] ${label}`, {
      at: new Date().toISOString(),
      ...detail,
    });
  } catch {
    // Debug logging must never affect chat behavior.
  }
}
