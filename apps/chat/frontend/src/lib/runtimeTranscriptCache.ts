import type { RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";

export type RuntimeTranscriptCacheEntry = {
  activeSession: RuntimeSession | null;
  activeTurn: RuntimeTurn | null;
  events: RuntimeEvent[];
  hasLoadedHistory: boolean;
  hasMoreHistory?: boolean;
  hasNewerHistory?: boolean;
};

/** Cold sessions only. The active transcript belongs to the mounted controller. */
export class RuntimeTranscriptCache {
  private entries = new Map<string, { entry: RuntimeTranscriptCacheEntry; bytes: number }>();
  private bytes = 0;
  constructor(private maxBytes = 32 * 1024 * 1024, private maxSessions = 8) {}

  get(session: string): RuntimeTranscriptCacheEntry | null {
    const value = this.entries.get(session);
    if (!value) return null;
    this.entries.delete(session);
    this.entries.set(session, value);
    return value.entry;
  }

  set(session: string, entry: RuntimeTranscriptCacheEntry): void {
    this.delete(session);
    // UTF-16 plus a conservative allowance for event objects, indexes and the
    // weakly held projection. Estimate only on navigation, never on each delta.
    const bytes = JSON.stringify(entry).length * 6 + entry.events.length * 256;
    if (bytes > this.maxBytes) return;
    this.entries.set(session, { entry, bytes });
    this.bytes += bytes;
    while (this.bytes > this.maxBytes || this.entries.size > this.maxSessions) this.delete(this.entries.keys().next().value!);
  }

  delete(session: string): void {
    const value = this.entries.get(session);
    if (!value) return;
    this.bytes -= value.bytes;
    this.entries.delete(session);
  }

  clear(): void { this.entries.clear(); this.bytes = 0; }
  get usage() { return { bytes: this.bytes, sessions: this.entries.size }; }
}
