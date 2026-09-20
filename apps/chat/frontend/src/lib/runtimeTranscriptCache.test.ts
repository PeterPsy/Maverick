import { expect, it } from 'vitest';
import { RuntimeTranscriptCache, type RuntimeTranscriptCacheEntry } from './runtimeTranscriptCache';

const entry = (size = 0): RuntimeTranscriptCacheEntry => ({ activeSession: null, activeTurn: null,
  hasLoadedHistory: true, events: size ? [{ event_id: 'one', session_id: 'one', event_type: 'runtime.output.final',
    created_at: '', turn_id: 'one', payload: { text: 'x'.repeat(size) } }] : [] });

it('bounds cold sessions by bytes and count and preserves recently accessed entries', () => {
  const cache = new RuntimeTranscriptCache(32 * 1024 * 1024, 8);
  for (let index = 0; index < 8; index++) cache.set(String(index), entry());
  const first = cache.get('0');
  cache.set('8', entry());
  expect(cache.get('1')).toBeNull();
  expect(cache.get('0')).toBe(first);
  expect(cache.usage.sessions).toBe(8);
  cache.set('large', entry(6 * 1024 * 1024));
  expect(cache.get('large')).toBeNull();
  expect(cache.usage.bytes).toBeLessThanOrEqual(32 * 1024 * 1024);
  cache.clear();
  expect(cache.usage).toEqual({ bytes: 0, sessions: 0 });
});
