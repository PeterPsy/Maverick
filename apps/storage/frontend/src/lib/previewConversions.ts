/** Two active conversions per Storage surface; aborted queued consumers never start. */
let active = 0;
const queue: Array<() => void> = [];

export function schedulePreviewConversion<T>(task: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  signal?.throwIfAborted();
  return new Promise<T>((resolve, reject) => {
    const abort = () => {
      const index = queue.indexOf(run);
      if (index >= 0) queue.splice(index, 1);
      reject(signal?.reason ?? new DOMException('Preview cancelled', 'AbortError'));
    };
    const run = () => {
      signal?.removeEventListener('abort', abort);
      if (signal?.aborted) { abort(); return; }
      active += 1;
      Promise.resolve().then(task).then(resolve, reject).finally(() => {
        active -= 1;
        queue.shift()?.();
      });
    };
    if (active < 2) run();
    else {
      queue.push(run);
      signal?.addEventListener('abort', abort, { once: true });
    }
  });
}
