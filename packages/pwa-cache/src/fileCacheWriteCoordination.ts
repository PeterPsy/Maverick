import { nativeCrossClientLocksAvailable, withCrossClientLock } from "./cacheBus";
import { combinedSignal } from "./fileCacheNetwork";
import type { FileCacheFilter } from "./fileCacheTypes";

const CHANNEL_NAME = "maverick-pwa-file-cache-writers-v1";
const WRITER_DRAIN_LOCK = "file-cache:active-writers";

type ActiveWrite = {
  controller: AbortController;
  done: Promise<void>;
  filter: FileCacheFilter;
  resolveDone: () => void;
};

type CancelMessage = {
  filter: FileCacheFilter;
  type: "cancel-writers";
};

const activeWrites = new Map<string, ActiveWrite>();
let channel: BroadcastChannel | null = null;

export function fileCacheCrossClientCoordinationAvailable(): boolean {
  return typeof window === "undefined" || nativeCrossClientLocksAvailable();
}

export async function runCoordinatedFileCacheWrite<T>(
  filter: FileCacheFilter,
  requestSignal: AbortSignal,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const id = globalThis.crypto?.randomUUID?.()
    ?? `file-write-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const controller = new AbortController();
  let resolveDone!: () => void;
  const done = new Promise<void>((resolve) => { resolveDone = resolve; });
  activeWrites.set(id, {
    controller,
    done,
    filter: structuredClone(filter),
    resolveDone,
  });
  ensureChannel();
  const signal = combinedSignal(requestSignal, controller.signal);
  try {
    return await withCrossClientLock(
      WRITER_DRAIN_LOCK,
      () => operation(signal),
      { mode: "shared", nativeOnly: true },
    );
  } finally {
    activeWrites.delete(id);
    resolveDone();
    closeIdleChannel();
  }
}

export async function cancelAndDrainFileCacheWriters(filter: FileCacheFilter): Promise<void> {
  cancelLocalWriters(filter);
  broadcastCancellation(filter);
  await drainLocalWriters(filter);
  if (nativeCrossClientLocksAvailable()) {
    await withCrossClientLock(
      WRITER_DRAIN_LOCK,
      async () => undefined,
      { mode: "exclusive", nativeOnly: true },
    );
  }
  await drainLocalWriters(filter);
}

function ensureChannel(): void {
  if (channel || typeof window === "undefined" || typeof globalThis.BroadcastChannel !== "function") return;
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.addEventListener("message", (event: MessageEvent<unknown>) => {
    const message = cancelMessage(event.data);
    if (message) cancelLocalWriters(message.filter);
  });
}

function broadcastCancellation(filter: FileCacheFilter): void {
  if (typeof window === "undefined" || typeof globalThis.BroadcastChannel !== "function") return;
  const broadcaster = new BroadcastChannel(CHANNEL_NAME);
  try {
    broadcaster.postMessage({ filter: structuredClone(filter), type: "cancel-writers" } satisfies CancelMessage);
  } finally {
    broadcaster.close();
  }
}

function cancelLocalWriters(filter: FileCacheFilter): void {
  for (const active of activeWrites.values()) {
    if (filtersOverlap(filter, active.filter) && !active.controller.signal.aborted) {
      active.controller.abort(new DOMException("File cache write cancelled by scoped cleanup.", "AbortError"));
    }
  }
}

async function drainLocalWriters(filter: FileCacheFilter): Promise<void> {
  while (true) {
    const pending = [...activeWrites.values()]
      .filter((active) => filtersOverlap(filter, active.filter))
      .map((active) => active.done);
    if (pending.length === 0) return;
    await Promise.allSettled(pending);
  }
}

function closeIdleChannel(): void {
  if (activeWrites.size > 0) return;
  channel?.close();
  channel = null;
}

function cancelMessage(value: unknown): CancelMessage | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const message = value as Partial<CancelMessage>;
  if (message.type !== "cancel-writers" || !validFilter(message.filter)) return null;
  return { filter: structuredClone(message.filter), type: "cancel-writers" };
}

function validFilter(value: unknown): value is FileCacheFilter {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const fields = new Set(["userId", "workspaceId", "appId", "fileId", "sourceVersion", "state"]);
  return Object.entries(record).every(([key, field]) => fields.has(key) && typeof field === "string");
}

function filtersOverlap(left: FileCacheFilter, right: FileCacheFilter): boolean {
  for (const field of ["userId", "workspaceId", "appId", "fileId", "sourceVersion", "state"] as const) {
    if (left[field] !== undefined && right[field] !== undefined && left[field] !== right[field]) return false;
  }
  return true;
}
