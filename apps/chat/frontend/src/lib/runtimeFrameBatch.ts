import type { RuntimeEvent } from '../api/client';

/** Only presentation waits for a frame; terminal/control events flush immediately. */
export function runtimeFrameBatch(consume: (events: RuntimeEvent[]) => void) {
  let queued: RuntimeEvent[] = [];
  let frame: number | null = null;
  let receivedText = false;
  let textTurn: string | null | undefined;
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
      if (event.event_type === 'runtime.output.delta' && event.payload?.text
        && (!receivedText || textTurn !== event.turn_id)) {
        receivedText = true;
        textTurn = event.turn_id;
        flush();
        return;
      }
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
