// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearQueuedMessageMemory, queueMemoryKey, readQueuedMessageState, rememberQueuedMessageState, transferQueuedMessages } from './queuedMessages';
const message = (clientMessageId: string) => ({ clientMessageId, content: 'text', attachments: [], appReferences: [] });
describe('document-only send state', () => {
  beforeEach(() => clearQueuedMessageMemory());
  it('separates navigation scopes and never writes private sends to browser storage', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const key = queueMemoryKey('a', 'draft');
    rememberQueuedMessageState(key, { queuedMessages: [message('one'), message('one')] });
    expect(readQueuedMessageState(key).queued).toHaveLength(1);
    expect(readQueuedMessageState(queueMemoryKey('b', 'draft')).queued).toEqual([]);
    expect(setItem).not.toHaveBeenCalled(); setItem.mockRestore();
  });
  it('transfers a live draft, de-duplicates buckets, and clears on teardown', () => {
    const pending = { ...message('one'), createdAt: '2026-09-05' };
    rememberQueuedMessageState(queueMemoryKey('', 'draft'), { pendingMessages: [pending], queuedMessages: [message('one'), message('two')] });
    transferQueuedMessages('', 'draft', 'thread');
    expect(readQueuedMessageState(queueMemoryKey('', 'draft')).pending).toEqual([]);
    expect(readQueuedMessageState(queueMemoryKey('', 'thread'))).toEqual({ pending: [pending], queued: [message('two')] });
    clearQueuedMessageMemory('');
    expect(readQueuedMessageState(queueMemoryKey('', 'thread')).queued).toEqual([]);
  });
});
