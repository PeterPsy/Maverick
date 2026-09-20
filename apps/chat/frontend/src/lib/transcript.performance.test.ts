import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { it } from 'vitest';
import type { RuntimeEvent } from '../api/client';
import { mergeRuntimeEvents } from './runtimeEvents';
import { clearTranscriptProjectionCache, eventsToMessages } from './transcript';

// Opt-in, isolated CPU probe; never a substitute for mounted browser/device traces.
it.skipIf(!process.env.MAVERICK_PERFORMANCE_PROBE)('measures live updates over 100/1000/5000 messages', () => {
  const results = [];
  for (const messages of [100, 1000, 5000]) {
    clearTranscriptProjectionCache();
    const event = (number: number, type: string, turn: number, payload: Record<string, unknown>): RuntimeEvent => ({
      event_id: `event-${number.toString().padStart(8, '0')}`, session_id: `probe-${messages}`, turn_id: `turn-${turn}`,
      created_at: new Date(Date.UTC(2026, 0, 1) + number).toISOString(), event_type: type, payload,
    });
    let events: RuntimeEvent[] = [];
    for (let turn = 0; turn < messages / 2; turn++) {
      events.push(event(turn * 2, 'runtime.turn.queued', turn, { input_text: 'Explain the latest result.' }));
      events.push(event(turn * 2 + 1, 'runtime.output.final', turn, { text: 'Verified result. '.repeat(32) }));
    }
    eventsToMessages(events);
    const times: number[] = [];
    const cpuStart = process.cpuUsage();
    for (let iteration = 0; iteration < 505; iteration++) {
      const start = performance.now();
      events = mergeRuntimeEvents(events, [event(messages + iteration, 'runtime.output.delta', messages, { text: 'A small live update. ' })]);
      eventsToMessages(events);
      if (iteration >= 5) times.push(performance.now() - start);
    }
    const cpu = process.cpuUsage(cpuStart);
    times.sort((a, b) => a - b);
    results.push({ messages, requests: 500, warmup: 5, median_ms: times[250], p95_ms: times[474], max_ms: times.at(-1), cpu_us: cpu.user + cpu.system });
  }
  writeFileSync(resolve(process.env.MAVERICK_PERFORMANCE_PROBE!), JSON.stringify({ scope: 'isolated-transcript-merge-and-projection', results }, null, 2));
}, 120_000);
