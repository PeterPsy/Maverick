const STORAGE_PREFIX = "loopino.chat.composerDraft.v1:";
const MAX_DRAFT_CHARS = 64 * 1024;
const MAX_DRAFTS = 20;
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

/** Core binds af-* origins to one user, workspace, app and platform session. */
export function composerDraftStorage(): Storage | null {
  if (!/^af-[a-f0-9]{24}\./.test(window.location.hostname)) return null;
  try { return window.localStorage; } catch { return null; }
}

export function composerDraftKey(workspace: string, windowScope: string, conversation: string): string {
  return STORAGE_PREFIX + JSON.stringify([workspace, windowScope, conversation]);
}

export function readComposerDraft(storage: Storage, key: string, now = Date.now()): string | null {
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (typeof value.text === "string" && value.text.length > 0 && value.text.length <= MAX_DRAFT_CHARS
        && Number.isFinite(value.updatedAt) && value.updatedAt <= now && value.updatedAt > now - MAX_AGE_MS) {
      return value.text;
    }
    storage.removeItem(key);
  } catch {
    try { storage.removeItem(key); } catch { /* Browser storage may be denied. */ }
  }
  return null;
}

export function writeComposerDraft(storage: Storage, key: string, text: string, now = Date.now()): void {
  try {
    if (!text.trim() || text.length > MAX_DRAFT_CHARS) {
      storage.removeItem(key);
      return;
    }
    const entries: Array<{ key: string; updatedAt: number }> = [];
    for (let index = 0; index < storage.length; index++) {
      const entryKey = storage.key(index);
      if (entryKey?.startsWith(STORAGE_PREFIX)) {
        entries.push({ key: entryKey, updatedAt: 0 });
      }
    }
    for (const entry of entries) {
      if (readComposerDraft(storage, entry.key, now) !== null) {
        entry.updatedAt = JSON.parse(storage.getItem(entry.key)!).updatedAt;
      }
    }
    const retained = entries.filter(entry => entry.updatedAt && entry.key !== key)
      .sort((left, right) => right.updatedAt - left.updatedAt);
    for (const entry of retained.slice(MAX_DRAFTS - 1)) storage.removeItem(entry.key);
    storage.setItem(key, JSON.stringify({ text, updatedAt: now }));
  } catch { /* A denied or full store leaves the live composer intact. */ }
}
