import { afterEach, expect, it, vi } from 'vitest';
import type { RuntimeEvent } from '../api/client';
import { runtimeFrameBatch } from './runtimeFrameBatch';

afterEach(() => vi.unstubAllGlobals());
it('coalesces deltas per frame, flushes terminals in order and drops disposed work', () => {
  let frame: FrameRequestCallback | null = null;
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback) => { frame = callback; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn(() => { frame = null; }));
  const consume = vi.fn();
  const batch = runtimeFrameBatch(consume);
  const event = (event_id: string, event_type = 'runtime.output.delta') => ({ event_id, event_type } as RuntimeEvent);
  for (let index = 0; index < 100; index++) batch.push(event(String(index)));
  expect(consume).not.toHaveBeenCalled();
  expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
  (frame as unknown as FrameRequestCallback)(16);
  expect(consume.mock.calls[0][0]).toHaveLength(100);
  batch.push(event('tail'));
  batch.push(event('final', 'runtime.output.final'));
  expect(consume.mock.calls[1][0].map((event: RuntimeEvent) => event.event_id)).toEqual(['tail', 'final']);
  batch.push(event('late'));
  batch.dispose();
  batch.flush();
  expect(consume).toHaveBeenCalledTimes(2);
});
