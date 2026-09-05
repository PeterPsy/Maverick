import type { PendingMessage, QueuedMessage } from './messageState';
type MessageState = { pending: PendingMessage[]; queued: QueuedMessage[] };
// Document-only UI state. Reload, principal teardown and close never replay sends.
const states = new Map<string, MessageState>();
export function queueMemoryKey(scope: string, conversation: string): string {
  return JSON.stringify([scope || 'main', conversation || 'none']);
}
export function clearQueuedMessageMemory(scope?: string): void {
  if (scope === undefined) states.clear();
  else for (const key of states.keys()) if (JSON.parse(key)[0] === (scope || 'main')) states.delete(key);
}
export function readQueuedMessageState(key: string): MessageState { return structuredClone(states.get(key) ?? { pending: [], queued: [] }); }
export function readQueuedMessages(key: string): QueuedMessage[] { return readQueuedMessageState(key).queued; }
export function readPendingMessages(key: string): PendingMessage[] { return readQueuedMessageState(key).pending; }
export function readRecoverableQueuedMessages(key: string): QueuedMessage[] {
  const state = readQueuedMessageState(key); return dedupe([...state.pending, ...state.queued]);
}
export function rememberQueuedMessages(key: string, queuedMessages: QueuedMessage[]): void { rememberQueuedMessageState(key, { queuedMessages }); }
export function rememberQueuedMessageState(key: string, { pendingMessages = [], queuedMessages = [] }: { pendingMessages?: PendingMessage[]; queuedMessages?: QueuedMessage[] }): void {
  const pending = dedupe(pendingMessages);
  const pendingIds = new Set(pending.map((item) => item.clientMessageId));
  const queued = dedupe(queuedMessages).filter((item) => !pendingIds.has(item.clientMessageId));
  if (!pending.length && !queued.length) states.delete(key);
  else states.set(key, structuredClone({ pending, queued }));
}
export function transferQueuedMessages(scope: string, from: string, to: string): void {
  if (!from || !to || from === to) return;
  const source = readQueuedMessageState(queueMemoryKey(scope, from));
  const target = readQueuedMessageState(queueMemoryKey(scope, to));
  rememberQueuedMessageState(queueMemoryKey(scope, to), { pendingMessages: [...target.pending, ...source.pending], queuedMessages: [...target.queued, ...source.queued] });
  states.delete(queueMemoryKey(scope, from));
}
function dedupe<T extends QueuedMessage>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => { if (seen.has(item.clientMessageId)) return false; seen.add(item.clientMessageId); return true; });
}
