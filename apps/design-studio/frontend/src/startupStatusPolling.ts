export function startNonOverlappingPoll<T>({
  intervalMs,
  onResult,
  poll,
}: {
  intervalMs: number;
  onResult: (result: T) => void;
  poll: () => Promise<T>;
}): () => void {
  let stopped = false;
  let timerId: ReturnType<typeof globalThis.setTimeout> | null = null;

  async function run(): Promise<void> {
    try {
      const result = await poll();
      if (!stopped) {
        onResult(result);
      }
    } catch {
      // Startup status is advisory; a later bounded poll may recover.
    } finally {
      if (!stopped) {
        timerId = globalThis.setTimeout(() => {
          timerId = null;
          void run();
        }, intervalMs);
      }
    }
  }

  void run();
  return () => {
    stopped = true;
    if (timerId !== null) {
      globalThis.clearTimeout(timerId);
      timerId = null;
    }
  };
}
