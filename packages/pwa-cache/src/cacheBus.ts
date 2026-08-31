export type CacheBusMessage =
  | { type: "all-cleared" }
  | { appId: string; entityId?: string; resource: string; type: "data-changed"; userId: string; workspaceId: string }
  | { appId?: string; type: "scope-cleared"; userId: string; workspaceId?: string }
  | { key: string; type: "entry-changed" };

type CacheBusListener = (message: CacheBusMessage) => void;

const CHANNEL_NAME = "maverick-pwa-cache-v1";

export class CacheBus {
  private readonly channel: BroadcastChannel | null;
  private readonly listeners = new Set<CacheBusListener>();

  constructor(channelFactory: ((name: string) => BroadcastChannel) | null = defaultChannelFactory()) {
    this.channel = channelFactory ? channelFactory(CHANNEL_NAME) : null;
    if (this.channel) {
      this.channel.onmessage = (event: MessageEvent<unknown>) => {
        if (isCacheBusMessage(event.data)) {
          this.emit(event.data);
        }
      };
    }
  }

  publish(message: CacheBusMessage): void {
    this.emit(message);
    try {
      this.channel?.postMessage(message);
    } catch {
      // Coordination is best-effort; cache correctness never depends on it.
    }
  }

  subscribe(listener: CacheBusListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  close(): void {
    this.channel?.close();
    this.listeners.clear();
  }

  private emit(message: CacheBusMessage): void {
    this.listeners.forEach((listener) => listener(message));
  }
}

export async function withCrossClientLock<T>(key: string, operation: () => Promise<T>): Promise<T> {
  const locks = globalThis.navigator && "locks" in globalThis.navigator
    ? (globalThis.navigator as Navigator & { locks?: LockManager }).locks
    : undefined;
  if (!locks || typeof locks.request !== "function") {
    return operation();
  }
  return locks.request(`maverick-pwa-cache:${stableHash(key)}`, operation);
}

function defaultChannelFactory(): ((name: string) => BroadcastChannel) | null {
  return typeof globalThis.BroadcastChannel === "function" ? (name) => new BroadcastChannel(name) : null;
}

function isCacheBusMessage(value: unknown): value is CacheBusMessage {
  if (!value || typeof value !== "object") {
    return false;
  }
  const type = (value as { type?: unknown }).type;
  return type === "all-cleared" || type === "data-changed" || type === "scope-cleared" || type === "entry-changed";
}

function stableHash(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}
