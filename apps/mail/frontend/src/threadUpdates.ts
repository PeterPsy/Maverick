import type { MailThread } from './api';

const keys = new Map<string, Promise<string>>();
/** Opaque entity hints match the hashes published by Mail's backend. */
export function threadScopeKey(id: string) {
  if (!keys.has(id)) keys.set(id, crypto.subtle.digest('SHA-256', new TextEncoder().encode(`mail:thread:${id}`))
    .then((buffer) => [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('')));
  return keys.get(id)!;
}

/** Read/label mutations update metadata while retaining the rendered body. */
export function mergeThreadState(current: MailThread, next: MailThread): MailThread {
  return { ...current, ...next, messages: current.messages?.map((message) => ({
    ...message, labels: next.messages?.find((item) => item.id === message.id)?.labels ?? message.labels,
  })) };
}
