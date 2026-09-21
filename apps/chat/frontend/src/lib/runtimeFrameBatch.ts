import type { RuntimeEvent } from '../api/client';

/** Only presentation waits for a frame; terminal/control events flush immediately. */
export function runtimeFrameBatch(consume: (events: RuntimeEvent[]) => void) {
  let queued: RuntimeEvent[] = [];
  let frame: number | null = null;
  let remainingFrames = 0;
  let receivedText = false;
  let textTurn: string | null | undefined;
  const flush = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    remainingFrames = 0;
    const events = queued;
    queued = [];
    if (events.length) consume(events);
  };
  const advanceFrame = () => {
    frame = null;
    remainingFrames -= 1;
    if (remainingFrames > 0) {
      frame = requestAnimationFrame(advanceFrame);
      return;
    }
    flush();
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
        // One animation frame still paints nearly every 20 ms provider delta on
        // a 60 Hz display. Present first text immediately, then span three paint
        // opportunities so adjacent deltas share one React commit without a
        // fixed timer or delaying terminal/control events.
        if (frame === null) {
          remainingFrames = 3;
          frame = requestAnimationFrame(advanceFrame);
        }
      } else flush();
    },
    flush,
    dispose() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      remainingFrames = 0;
      queued = [];
    },
  };
}
