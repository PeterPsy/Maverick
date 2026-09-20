import type { PreviewTablePayload } from '../types';

export type PreviewValue = { text: string; url: string; table?: PreviewTablePayload; bytes?: number };
export type PreviewLease = PreviewValue & { release(): void };
type Entry = { value: PreviewValue; bytes: number; pins: number; cached: boolean; revoked: boolean };

/** Completed values only. Mounted consumers pin blob URLs until their lease ends. */
export class PreviewMemoryCache {
  private readonly entries = new Map<string, Entry>();
  private readonly live = new Set<Entry>();
  private bytes = 0;

  constructor(private readonly maximumBytes = 32 * 1024 * 1024, private readonly maximumEntryBytes = 8 * 1024 * 1024) {}

  get(key: string, signal?: AbortSignal): PreviewLease | null {
    signal?.throwIfAborted();
    const entry = this.entries.get(key);
    if (!entry) return null;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return this.lease(entry, signal);
  }

  remember(key: string, value: PreviewValue, signal?: AbortSignal): PreviewLease {
    if (signal?.aborted) {
      this.revoke(value);
      signal.throwIfAborted();
    }
    const existing = this.get(key, signal);
    if (existing) {
      this.revoke(value);
      return existing;
    }
    const bytes = 256 + key.length * 2 + (value.bytes ?? (value.text.length * 2 + value.url.length * 2
      + (value.table ? JSON.stringify(value.table).length * 2 : 0)));
    const entry: Entry = { value, bytes, pins: 0, cached: false, revoked: false };
    if (bytes <= this.maximumEntryBytes) {
      for (const [oldKey, old] of this.entries) {
        if (this.bytes + bytes <= this.maximumBytes) break;
        if (old.pins > 0) continue;
        this.entries.delete(oldKey);
        this.bytes -= old.bytes;
        old.cached = false;
        this.dispose(old);
      }
      if (this.bytes + bytes <= this.maximumBytes) {
        this.entries.set(key, entry);
        this.bytes += bytes;
        entry.cached = true;
      }
    }
    this.live.add(entry);
    return this.lease(entry, signal);
  }

  clear(): void {
    this.entries.clear();
    this.bytes = 0;
    for (const entry of this.live) {
      entry.cached = false;
      this.dispose(entry);
    }
  }

  private lease(entry: Entry, signal?: AbortSignal): PreviewLease {
    entry.pins += 1;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      signal?.removeEventListener('abort', release);
      entry.pins -= 1;
      if (!entry.cached) this.dispose(entry);
    };
    signal?.addEventListener('abort', release, { once: true });
    return { ...entry.value, release };
  }

  private dispose(entry: Entry): void {
    if (entry.revoked) return;
    entry.revoked = true;
    this.revoke(entry.value);
    this.live.delete(entry);
  }

  private revoke(value: PreviewValue): void {
    if (value.url.startsWith('blob:')) URL.revokeObjectURL(value.url);
  }
}
