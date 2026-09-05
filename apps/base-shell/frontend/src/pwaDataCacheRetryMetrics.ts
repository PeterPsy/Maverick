import type { RetryTelemetryEvent } from "@maverick/pwa-cache";

type Wait = { attempt: number; closed: boolean; startedAt: number };
const MAX_READ_TRANSPORTS = 16;

/** One private network request, bounded and re-keyed by the host. */
export class PwaDataCacheRetryMetrics {
  private readonly waits = new Map<string, Wait>();
  private closed = false;

  constructor(
    private readonly networkId: string,
    private readonly record: (event: RetryTelemetryEvent) => void,
    private readonly now: () => number = () => Date.now(),
  ) {}

  receive(event: RetryTelemetryEvent): void {
    if (this.closed) return;
    const wait = this.waits.get(event.keyHash);
    if (event.kind === "wait_started") {
      if (wait || this.waits.size >= MAX_READ_TRANSPORTS || event.attempt !== 0) return;
      this.waits.set(event.keyHash, { attempt: 0, closed: false, startedAt: this.now() });
      this.record({ attempt: 0, keyHash: this.key(event.keyHash), kind: "wait_started" });
      return;
    }
    if (!wait || wait.closed) return;
    if (event.kind === "retry_attempt") {
      if (event.attempt !== wait.attempt + 1) return;
      wait.attempt = event.attempt;
      this.record({ attempt: wait.attempt, keyHash: this.key(event.keyHash), kind: "retry_attempt" });
    } else if (event.attempt === wait.attempt) {
      this.complete(event.keyHash, wait, event.kind);
    }
  }

  close(kind: "cancelled" | "resolved"): void {
    if (this.closed) return;
    this.closed = true;
    // Host cancellation may close the port before the child's final event.
    for (const [key, wait] of this.waits) if (!wait.closed) this.complete(key, wait, kind);
    this.waits.clear();
  }

  private complete(key: string, wait: Wait, kind: "cancelled" | "resolved"): void {
    wait.closed = true;
    this.record({
      attempt: wait.attempt, keyHash: this.key(key), kind,
      durationMs: Math.max(0, this.now() - wait.startedAt),
    });
  }

  private key(childHash: string): string {
    return `${this.networkId}:${childHash}`;
  }
}
