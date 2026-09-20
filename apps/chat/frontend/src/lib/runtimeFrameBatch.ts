import type { RuntimeEvent } from '../api/client';

/** Only presentation waits for a frame; terminal/control events flush immediately. */
export function runtimeFrameBatch(consume: (events: RuntimeEvent[]) => void) {
  let queued: RuntimeEvent[] = [];
  let frame: number | null = null;
  const flush = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    const events = queued;
    queued = [];
    if (events.length) consume(events);
  };
  return {
    push(event: RuntimeEvent) {
      queued.push(event);
      if (['runtime.output.delta', 'runtime.tool_call.updated', 'runtime.step.updated'].includes(event.event_type)) {
        if (frame === null) frame = requestAnimationFrame(flush);
      } else flush();
    },
    flush,
    dispose() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      queued = [];
    },
  };
}
