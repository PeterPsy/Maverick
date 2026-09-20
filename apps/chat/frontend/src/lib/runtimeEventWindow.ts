import type { RuntimeEvent } from '../api/client';

export const RUNTIME_WINDOW_EVENTS = 6000;
export const RUNTIME_WINDOW_BYTES = 32 * 1024 * 1024;
const eventBytes = new WeakMap<RuntimeEvent, number>();
const windowBytes = new WeakMap<RuntimeEvent[], number>();

function size(event: RuntimeEvent): number {
  let bytes = eventBytes.get(event);
  if (bytes === undefined) {
    // UTF-16 strings, object/index overhead and the derived projection. This is
    // an accounting allowance, not a browser-specific measurement of the heap.
    bytes = JSON.stringify(event).length * 6 + 256;
    eventBytes.set(event, bytes);
  }
  return bytes;
}

/** Keep a contiguous, reloadable window. The live turn may exceed its budget. */
export function boundRuntimeEventWindow(
  events: RuntimeEvent[],
  { keep = 'latest', activeTurnId = null, previous, maxEvents = RUNTIME_WINDOW_EVENTS, maxBytes = RUNTIME_WINDOW_BYTES }: {
    keep?: 'earliest' | 'latest'; activeTurnId?: string | null; previous?: RuntimeEvent[];
    maxEvents?: number; maxBytes?: number;
  } = {},
) {
  let bytes = windowBytes.get(events);
  if (bytes === undefined) {
    const previousBytes = previous && windowBytes.get(previous);
    const extendsPrevious = previous && previousBytes !== undefined && previous.length <= events.length
      && previous.every((event, index) => event === events[index]);
    bytes = extendsPrevious ? previousBytes : 0;
    for (let index = extendsPrevious ? previous.length : 0; index < events.length; index++) bytes += size(events[index]);
    windowBytes.set(events, bytes);
  }
  if (events.length <= maxEvents && bytes <= maxBytes) return { events, removedBefore: false, removedAfter: false, bytes };

  // Leave room for the next batches so eviction doesn't rebuild indexes for
  // every delta. Prefer turn boundaries, but very large historical turns remain
  // pageable in parts instead of making the cold window unbounded.
  const targetEvents = Math.max(1, Math.floor(maxEvents * 0.8));
  const targetBytes = maxBytes * 0.8;
  let start = 0;
  let end = events.length;
  const activeStart = keep === 'latest' && activeTurnId ? events.findIndex(event => event.turn_id === activeTurnId) : -1;
  if (keep === 'latest') {
    while (end - start > 1 && (end - start > targetEvents || bytes > targetBytes)) {
      if (start === activeStart) break;
      bytes -= size(events[start++]);
    }
    const boundary = start;
    while (start > 0 && start < end - 1 && start !== activeStart
      && events[start].turn_id && events[start].turn_id === events[start - 1].turn_id) start++;
    // A single historical turn can occupy the entire page.
    if (start === end - 1) start = boundary;
  } else {
    while (end - start > 1 && (end - start > targetEvents || bytes > targetBytes)) bytes -= size(events[--end]);
    const boundary = end;
    while (end > 1 && events[end]?.turn_id && events[end].turn_id === events[end - 1].turn_id) end--;
    if (end === 1) end = boundary;
  }
  const selected = start === 0 && end === events.length ? events : events.slice(start, end);
  bytes = selected.reduce((total, event) => total + size(event), 0);
  windowBytes.set(selected, bytes);
  return { events: selected, removedBefore: start > 0, removedAfter: end < events.length, bytes };
}
