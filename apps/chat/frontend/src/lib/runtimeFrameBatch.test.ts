import { afterEach, expect, it, vi } from 'vitest';
import type { RuntimeEvent } from '../api/client';
import { runtimeFrameBatch } from './runtimeFrameBatch';

afterEach(() => vi.unstubAllGlobals());
it('presents first text immediately, coalesces later deltas and flushes terminals in order', () => {
  let frame: FrameRequestCallback | null = null;
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback) => { frame = callback; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn(() => { frame = null; }));
  const consume = vi.fn();
  const batch = runtimeFrameBatch(consume);
  const event = (event_id: string, event_type = 'runtime.output.delta'): RuntimeEvent => ({
    event_id, event_type, turn_id: 'turn', session_id: 'session', created_at: '', payload: { text: 'Text' },
  });
  batch.push(event('first'));
  expect(consume.mock.calls[0][0].map((item: RuntimeEvent) => item.event_id)).toEqual(['first']);
  expect(requestAnimationFrame).not.toHaveBeenCalled();
  for (let index = 0; index < 100; index++) batch.push(event(String(index)));
  expect(consume).toHaveBeenCalledTimes(1);
  expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
  (frame as unknown as FrameRequestCallback)(16);
  expect(consume.mock.calls[1][0]).toHaveLength(100);
  batch.push(event('tail'));
  batch.push(event('final', 'runtime.output.final'));
  expect(consume.mock.calls[2][0].map((event: RuntimeEvent) => event.event_id)).toEqual(['tail', 'final']);
  batch.push(event('late'));
  batch.dispose();
  batch.flush();
  expect(consume).toHaveBeenCalledTimes(3);
});

it('preserves queued updates before the first text of each turn', () => {
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  const consume = vi.fn();
  const batch = runtimeFrameBatch(consume);
  const delta = (turn_id: string, text: string): RuntimeEvent => ({
    event_id: `${turn_id}-${text}`, session_id: 'session', created_at: '',
    turn_id, event_type: 'runtime.output.delta', payload: { text },
  });
  const empty = delta('first', '');
  batch.push(empty);
  expect(consume).not.toHaveBeenCalled();
  const first = delta('first', 'First text');
  batch.push(first);
  expect(consume).toHaveBeenLastCalledWith([empty, first]);
  const tail = delta('first', ' tail');
  batch.push(tail);
  expect(consume).toHaveBeenCalledTimes(1);
  const next = delta('second', 'Next turn');
  batch.push(next);
  expect(consume).toHaveBeenLastCalledWith([tail, next]);
  batch.dispose();
});
