import { describe, expect, it } from 'vitest';
import type { RuntimeEvent } from '../api/client';
import { boundRuntimeEventWindow } from './runtimeEventWindow';

const events = (count: number) => Array.from({ length: count }, (_, index): RuntimeEvent => ({
  event_id: `event-${index}`, session_id: 'session', turn_id: `turn-${Math.floor(index / 4)}`,
  event_type: 'runtime.output.delta', created_at: String(index), payload: { text: 'hello' },
}));

describe('runtime event data window', () => {
  it('keeps contiguous windows in both directions and preserves retained identities', () => {
    const all = events(100);
    const latest = boundRuntimeEventWindow(all, { maxEvents: 20 });
    const earlier = boundRuntimeEventWindow(all, { maxEvents: 20, keep: 'earliest' });
    expect(latest.events).toEqual(all.slice(84));
    expect(earlier.events).toEqual(all.slice(0, 16));
    expect(latest.events[0]).toBe(all[84]);
    expect(latest.removedBefore).toBe(true);
    expect(earlier.removedAfter).toBe(true);
  });
  it('bounds large completed turns by bytes and retains one oversized event', () => {
    const all = events(20).map(event => ({ ...event, turn_id: 'one', payload: { text: 'x'.repeat(1000) } }));
    const page = boundRuntimeEventWindow(all, { maxBytes: 20000 });
    expect(page.bytes).toBeLessThanOrEqual(20000);
    expect(page.events.at(-1)).toBe(all.at(-1));
    expect(boundRuntimeEventWindow(all, { maxBytes: 1 }).events).toHaveLength(1);
  });
  it('pins the complete active turn and releases it when the turn ends', () => {
    const all = events(100).map((event, index) => index >= 20 ? { ...event, turn_id: 'active' } : event);
    const live = boundRuntimeEventWindow(all, { maxEvents: 20, activeTurnId: 'active' });
    expect(live.events).toEqual(all.slice(20));
    expect(boundRuntimeEventWindow(live.events, { maxEvents: 20 }).events.length).toBeLessThanOrEqual(20);
  });
  it('does not copy or reserialize retained events on ordinary append', () => {
    const all = events(20);
    const initial = all.slice(0, 10);
    boundRuntimeEventWindow(initial);
    const result = boundRuntimeEventWindow(all, { previous: initial });
    expect(result.events).toBe(all);
    expect(result.removedBefore || result.removedAfter).toBe(false);
  });
});
