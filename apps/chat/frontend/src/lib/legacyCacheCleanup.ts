const prefixes = ['maverick.chat.projects-cache.v1:', 'maverick.chat.runtime-transcript-cache.v2:', 'maverick.chat.queued-messages.v1:'];
/** Unscoped display data, runtime authority and old send queues are deleted, never imported. */
export function purgeLegacyChatCaches(): void {
  if (typeof window === 'undefined') return;
  for (const name of ['localStorage', 'sessionStorage'] as const) {
    try {
      const storage = window[name];
      const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index));
      for (const key of keys) if (key && prefixes.some((prefix) => key.startsWith(prefix))) storage.removeItem(key);
    } catch { /* Denied storage cannot be used as a migration source either. */ }
  }
}
